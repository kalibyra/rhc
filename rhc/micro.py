from importlib import import_module
import sys
import traceback

from rhc.log import logmsg
from rhc.tcpsocket import Server
from rhc.resthandler import RESTMapper, RESTHandler


SERVER = Server()


def _import(item_path):
    path, function = item_path.rsplit('.', 1)
    module = import_module(path)
    return getattr(module, function)


def _load(f):

    result = dict(
        routes=[],
        context=None,
        port=None,
    )

    kwargs = None
    for lnum, l in enumerate((ll for ll in (l.split('#', 1)[0].strip() for l in f.readlines()) if len(ll)), start=1):
        if l.find(' ') == -1:
            raise Exception("Line %d doesn't contain a space" % lnum)
        rectyp, recval = l.split(' ', 1)
        rectyp = rectyp.upper()
        recval = recval.strip()

        if rectyp == 'ROUTE':
            kwargs = {}
            result['routes'].append((recval.strip(), kwargs))
        elif rectyp in ('GET', 'PUT', 'POST', 'DELETE'):
            if kwargs is None:
                raise Exception("Line %d contains a %s that doesn't belong to a ROUTE" % (lnum, rectyp))
            kwargs[rectyp.lower()] = _import(recval)
        elif rectyp == 'CONTEXT':
            kwargs = None
            result['context'] = _import(recval)()
        elif rectyp == 'PORT':
            kwargs = None
            result['port'] = int(recval)
        else:
            raise Exception("Line %d is an invalid record type: %s" % (lnum, rectyp))

    return result


class MicroRESTHandler(RESTHandler):

    NEXT_ID = 0
    NEXT_REQUEST_ID = 0

    def on_open(self):
        self.id = MicroRESTHandler.NEXT_ID = MicroRESTHandler.NEXT_ID + 1
        logmsg(102, self.id, self.full_address())

    def on_close(self):
        logmsg(103, self.id, self.full_address())

    def on_rest_data(self, request, *groups):
        request.id = MicroRESTHandler.NEXT_REQUEST_ID = MicroRESTHandler.NEXT_REQUEST_ID + 1
        logmsg(104, self.id, request.id, request.http_method, request.http_resource, request.http_query_string, groups)

    def on_rest_exception(self, exception_type, value, trace):
        data = traceback.format_exc(trace)
        logmsg(105, data)
        return data


if __name__ == '__main__':
    from StringIO import StringIO
    from rhc.log import LOG

    LOG.setup(StringIO('''
        MESSAGE 100
        LOG     INFO
        DISPLAY ALWAYS
        TEXT Server listening on port %s

        MESSAGE 101
        LOG     INFO
        DISPLAY ALWAYS
        TEXT Received shutdown command from keyboard

        MESSAGE 102
        LOG     INFO
        DISPLAY ALWAYS
        TEXT open: cid=%d, %s

        MESSAGE 103
        LOG     INFO
        DISPLAY ALWAYS
        TEXT close: cid=%d, %s

        MESSAGE 104
        LOG     INFO
        DISPLAY ALWAYS
        TEXT request cid=%d, rid=%d, method=%s, resource=%s, query=%s, groups=%s

        MESSAGE 105
        LOG     WARNING
        DISPLAY ALWAYS
        TEXT exception encountered: %s

    '''), stdout=True)

    f = sys.stdin if len(sys.argv) < 2 else open(sys.argv[1])
    config = _load(f)

    m = RESTMapper(context=config['context'])
    for pattern, kwargs in config['routes']:
        m.add(pattern, **kwargs)

    SERVER.add_server(config['port'], MicroRESTHandler, m)
    logmsg(100, config['port'])
    try:
        while True:
            SERVER.service(.1)
    except KeyboardInterrupt:
        print 'done'
