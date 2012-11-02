import datetime as dt
import inspect
import logging
import os
import pprint
import socket
import sys
import tempfile
import thread
import linecache

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.core.mail.message import EmailMessage
from django.core.urlresolvers import resolve, Resolver404

from dogslow.timer import Timer

_sentinel = object()
def safehasattr(obj, name):
    return getattr(obj, name, _sentinel) is not _sentinel

class SafePrettyPrinter(pprint.PrettyPrinter, object):
    def format(self, obj, context, maxlevels, level):
        try:
            return super(SafePrettyPrinter, self).format(
                obj, context, maxlevels, level)
        except Exception:
            return object.__repr__(obj)[:-1] + ' (bad repr)>', True, False

def spformat(obj, depth=None):
    return SafePrettyPrinter(indent=1, width=76, depth=depth).pformat(obj)

def formatvalue(v):
    s = spformat(v, depth=1).replace('\n', '')
    if len(s) > 250:
        s = object.__repr__(v)[:-1] + ' (really long repr)>'
    return '=' + s

def stack(f, with_locals=False):
    limit = getattr(sys, 'tracebacklimit', None)

    frames = []
    n = 0
    while f is not None and (limit is None or n < limit):
        lineno, co = f.f_lineno, f.f_code
        name, filename = co.co_name, co.co_filename
        args = inspect.getargvalues(f)

        linecache.checkcache(filename)
        line = linecache.getline(filename, lineno, f.f_globals)
        if line:
            line = line.strip()
        else:
            line = None

        frames.append((filename, lineno, name, line, f.f_locals, args))
        f = f.f_back
        n += 1
    frames.reverse()

    out = []
    for filename, lineno, name, line, localvars, args in frames:
        out.append('  File "%s", line %d, in %s' % (filename, lineno, name))
        if line:
            out.append('    %s' % line.strip())

        if with_locals:
            args = inspect.formatargvalues(formatvalue=formatvalue, *args)
            out.append('\n      Arguments: %s%s' % (name, args))

        if with_locals and localvars:
            out.append('      Local variables:\n')
            try:
                reprs = spformat(localvars)
            except Exception:
                reprs = "failed to format local variables"
            out += ['      ' + l for l in reprs.splitlines()]
            out.append('')
    return '\n'.join(out)

class WatchdogMiddleware(object):

    def __init__(self):
        if not getattr(settings, 'DOGSLOW', True):
            raise MiddlewareNotUsed
        else:
            # allow floating points to cater for millisecond precision
            self.interval = float(getattr(settings, 'DOGSLOW_TIMER', 25))
            self.timer = Timer()
            self.timer.setDaemon(True)
            self.timer.start()

    @staticmethod
    def peek(request, thread_id, started):
        try:
            frame = sys._current_frames()[thread_id]

            req_string = '%s %s://%s%s' % (
                request.META.get('REQUEST_METHOD'),
                request.META.get('wsgi.url_scheme', 'http'),
                request.META.get('HTTP_HOST'),
                request.META.get('PATH_INFO'),
            )
            if request.META.get('QUERY_STRING', ''):
                req_string += ('?' + request.META.get('QUERY_STRING'))

            output = 'Undead request intercepted at: %s\n\n' \
                '%s\n' \
                'Hostname:   %s\n' \
                'Thread ID:  %d\n' \
                'Process ID: %d\n' \
                'Started:    %s\n\n' % \
                    (dt.datetime.utcnow().strftime("%d-%m-%Y %H:%M:%S UTC"),
                     req_string,
                     socket.gethostname(),
                     thread_id,
                     os.getpid(),
                     started.strftime("%d-%m-%Y %H:%M:%S UTC"),)

            output += stack(frame, with_locals=False)
            output += '\n\n'

            stack_vars = getattr(settings, 'DOGSLOW_STACK_VARS', False)
            if not stack_vars:
                # no local stack variables
                output += ('This report does not contain the local stack '
                           'variables.\n'
                           'To enable this (very verbose) information, add '
                           'this to your Django settings:\n'
                           '  DOGSLOW_STACK_VARS=True\n')
            else:
                output += 'Full backtrace with local variables:'
                output += '\n\n'
                output += stack(frame, with_locals=True)

            output = output.encode('utf-8')

            # Default to None to allow local logs to be omitted
            local_path = getattr(settings, 'DOGSLOW_OUTPUT', None)
            
            if local_path is not None:
                # dump to file:
                fd = tempfile.mkstemp(prefix='slow_request_', suffix='.log', dir=local_path)
                try:
                    os.write(fd, output)
                finally:
                    os.close(fd)

            # and email?
            email_to = getattr(settings, 'DOGSLOW_EMAIL_TO', None)
            email_from = getattr(settings, 'DOGSLOW_EMAIL_FROM', None)
            if email_to is not None and email_from is not None:
                em = EmailMessage('Slow Request Watchdog: %s' %
                                  req_string.encode('utf-8'),
                                  output,
                                  email_from,
                                  (email_to,))
                em.send(fail_silently=True)

            # and a custom logger:
            logger_name = getattr(settings, 'DOGSLOW_LOGGER', None)
            log_level = getattr(settings, 'DOGSLOW_LOG_LEVEL', 'WARNING')
            if logger_name is not None:
                log_level = logging.getLevelName(log_level)
                logger = logging.getLogger(logger_name)

                logger.log(log_level, 'Slow Request Watchdog: %s, %s - %s',
                           resolve(request.META.get('PATH_INFO')).url_name,
                           req_string.encode('utf-8'),
                           output,
                           # we're passing the Django request object along
                           # with the log call in case we're being used with
                           # Sentry:
                           extra={'request': request})

        except Exception:
            logging.exception('Request watchdog failed')

    def _is_exempt(self, request):
        """Returns True if this request's URL resolves to a url pattern whose
        name is listed in settings.DOGSLOW_IGNORE_URLS.
        """
        try:
            match = resolve(request.META.get('PATH_INFO'))
        except Resolver404:
            return False
        return match and (match.url_name in
                       getattr(settings, 'DOGSLOW_IGNORE_URLS', ()))

    def process_request(self, request):
        if not self._is_exempt(request):
            request.dogslow = self.timer.run_later(
                WatchdogMiddleware.peek,
                self.interval,
                request,
                thread.get_ident(),
                dt.datetime.utcnow())

    def _cancel(self, request):
        try:
            if safehasattr(request, 'dogslow'):
                self.timer.cancel(request.dogslow)
                del request.dogslow
        except:
            logging.exception('Failed to cancel request watchdog')

    def process_response(self, request, response):
        self._cancel(request)
        return response

    def process_exception(self, request, exception):
        self._cancel(request)