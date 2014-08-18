'''
The MIT License (MIT)

Copyright (c) 2013-2014 Robert H Chase

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
'''
from tcpsocket import BasicHandler

import time
import urlparse


class HTTPHandler(BasicHandler):

    def __init__(self, socket, context=None):
        '''
            Handler for an HTTP connection.

                available variables (on_http_data)

                    http_message - entire message
                    http_headers - dictionary of headers
                    http_content - content
                    error - any error message

                    client:
                        http_status_code - integer code from status line
                        http_status_message - message from status line

                    server:
                        http_method - method from status line
                        http_multipart - list of HTTPPart objects
                        http_resource - resource from status line
                        http_query_string - unmodified query string
                        http_query - dict of query string

                on_http_send(self, headers, content) - useful for debugging
                on_http_data(self) - when data is available
                on_http_error(self)
        '''
        super(HTTPHandler, self).__init__(socket, context)
        self.__data = ''
        self.__setup()

    def on_http_send(self, headers, content):
        pass

    def on_http_data(self):
        pass

    def on_http_error(self):
        pass

    def _multipart(self):
        cache = self.__data
        try:
            self.http_headers['Content-Type'], boundary = self.http_headers['Content-Type'].split('; boundary=')
            for self.__data in [p[2:] for p in self.http_content.split('--' + boundary)][1:-1]:  # split, remove \r\n and ignore first & last; stuff into __data for __line
                headers = dict(l.split(': ', 1) for l in iter(self.__line, ''))
                if 'Content-Disposition' in headers:
                    headers['Content-Disposition'], rem = headers['Content-Disposition'].split('; ', 1)
                    disposition = dict(part.split('=', 1) for part in rem.split('; '))
                self.http_multipart.append(HTTPPart(headers, disposition, self.__data))
        except Exception:
            self.__error('Malformed multipart message')
        self.__data = cache

    def _on_http_data(self):
        if self.http_headers.get('Content-Type', '').startswith('multipart'):
            self._multipart()
        self.on_http_data()
        if self.http_headers.get('Connection') == 'close':
            self.close()

    def __send(self, headers, content):
        self.on_http_send(headers, content)
        super(HTTPHandler, self).send(headers + content)

    def send(self, method='GET', host=None, resource='/', headers=None,
             content='', close=False):

        if not headers:
            headers = {}

        if 'Date' not in headers:
            headers['Date'] = time.strftime(
                "%a, %d %b %Y %H:%M:%S %Z", time.localtime())

        if 'Content-Length' not in headers:
            headers['Content-Length'] = len(content)

        if close:
            headers['Connection'] = 'close'

        if not host:
            host = '%s:%s' % self.peer_address()

        headers = '%s %s HTTP/1.1\r\nHost: %s\r\n%s\r\n\r\n' % (
            method, resource, host,
            '\r\n'.join(['%s: %s' % (k, v) for k, v in headers.items()])
        )

        self.__send(headers, content)

    def send_server(self, content='', code=200, message='OK', headers=None):

        if headers is None:
            headers = {}

        if 'Date' not in headers:
            headers['Date'] = time.strftime(
                "%a, %d %b %Y %H:%M:%S %Z", time.localtime())

        if 'Content-Length' not in headers:
            headers['Content-Length'] = len(content)

        headers = 'HTTP/1.1 %d %s\r\n%s\r\n\r\n' % (
            code, message,
            '\r\n'.join(['%s: %s' % (k, v) for k, v in headers.items()]))

        self.__send(headers, content)

    def __setup(self):
        self.http_message = ''
        self.http_headers = {}
        self.http_content = ''
        self.http_status_code = None
        self.http_status_message = None
        self.http_method = None
        self.http_multipart = []
        self.http_resource = None
        self.http_query_string = None
        self.http_query = {}
        self.__state = self.__status

    def on_data(self, data):
        self.http_message += data
        self.__data += data
        while self.__state():
            pass

    def __error(self, message):
        self.error = message
        self.on_http_error()
        self.close()
        return False

    def __line(self):
        test = self.__data.split('\n', 1)
        if len(test) == 1:
            return None
        line, self.__data = test
        if len(line):
            if line[-1] == '\r':
                line = line[:-1]
        return line

    def __status(self):
        line = self.__line()
        if line is None:
            return False
        toks = line.split()
        if len(toks) < 3:
            return self.__error('Invalid status line: too few tokens')

        # HTTP/1.1 200 OK
        if toks[0] == 'HTTP/1.1':
            try:
                self.http_status_code = toks[1]
                self.http_status_code = int(self.http_status_code)
            except ValueError:
                return self.__error('Invalid status line: non-integer status code')
            self.http_status_message = ' '.join(toks[2:])

        # GET /resource HTTP/1.[0|1]
        else:
            if toks[2] not in ('HTTP/1.0', 'HTTP/1.1'):
                return self.__error('Invalid status line: not HTTP/1.0 or HTTP/1.1')
            self.http_method = toks[0]

            res = urlparse.urlparse(toks[1])
            self.http_resource = res.path
            self.http_query = {}
            self.http_query_string = ''
            if res.query:
                self.http_query_string = res.query
                for n, v in urlparse.parse_qsl(res.query):
                    self.http_query[n] = v

        self.__state = self.__header
        return True

    def __header(self):
        line = self.__line()
        if line is None:
            return False

        if len(line) == 0:
            if 'Transfer-Encoding' in self.http_headers:
                if self.http_headers['Transfer-Encoding'] != 'chunked':
                    return self.__error('Unsupported Transfer-Encoding value')
                self.__state = self.__chunked_length

            else:
                if 'Content-Length' in self.http_headers:
                    try:
                        self.__length = int(
                            self.http_headers['Content-Length'])
                    except ValueError:
                        return self.__error('Invalid content length')
                else:
                    self.__length = 0
                self.__state = self.__content

        else:
            test = line.split(':', 1)
            if len(test) != 2:
                return self.__error('Invalid header: missing colon')
            name, value = test
            self.http_headers[name.strip()] = value.strip()

        return True

    def __content(self):
        if len(self.__data) >= self.__length:
            self.http_content = self.__data[:self.__length]
            self._on_http_data()
            self.__data = self.__data[self.__length:]
            self.__setup()
            return True
        return False

    def __chunked_length(self):
        line = self.__line()
        if line is None:
            return False
        line = line.split(';', 1)[0]
        try:
            self.__length = int(line, 16)
        except ValueError:
            return self.__error('Invalid transfer-encoding chunk length: %s' % line)
        if self.__length == 0:
            self.__state = self.__footer
            return True
        self.__state = self.__chunked_content
        return True

    def __chunked_content(self):
        if len(self.__data) >= self.__length:
            self.http_content += self.__data[:self.__length]
            self.__data = self.__data[self.__length:]
            self.__state = self.__chunked_content_end
            return True
        return False

    def __chunked_content_end(self):
        line = self.__line()
        if line is None:
            return False
        if line == '':
            self.__state = self.__chunked_length
            return True
        return self.__error('Extra data at end of chunk')

    def __footer(self):
        line = self.__line()
        if line is None:
            return False

        if len(line) == 0:
            self._on_http_data()
            self.__setup()
            return True

        test = line.split(':', 1)
        if len(test) != 2:
            return self.__error('Invalid footer: missing colon')
        name, value = test
        self.http_headers[name.strip()] = value.strip()
        return True


class HTTPPart(object):

    def __init__(self, headers, disposition, content):
        '''
            Container for one part of a multipart message.

            The disposition is a dict with the k:v pairs from the 'Content-Disposition'
            header, where things like filename are stored.
        '''
        self.headers = headers
        self.disposition = disposition
        self.content = content