from wsgidav.middleware import BaseMiddleware
from wsgidav import compat, util

_logger = util.getModuleLogger(__name__, True)


class Authorizer(BaseMiddleware):
    def __init__(self, application, config):
        BaseMiddleware.__init__(self, application, config)
        self.application = application
        self.config = config

    def __call__(self, environ, start_response):
        userName = self.getUserName(environ)
        environ['WT_DAV_AUTHORIZED_USER'] = userName
        return self.checkAccess(userName, environ, start_response)

    def getUserName(self, environ):
        if 'TOKEN_USER' in environ:
            return environ['TOKEN_USER']['login']
        if 'http_authenticator.username' in environ:
            return environ['http_authenticator.username']
        return None

    def checkAccess(self, userName, environ, start_response):
        path = environ['PATH_INFO']
        if userName is None or userName == '':
            body = self.buildMustAuthenticateBody(path)
            return self.sendNotAuthorizedResponse(body, environ, start_response)
        # allow /<userName> and /<userName>/*
        # should probably check that login names don't allow things like '../../etc'
        if path == ('/%s' % userName) or path.startswith('/%s/' % userName):
            return self.application(environ, start_response)
        else:
            body = self.buildNotAuthorizedResponseBody(userName, path)
            return self.sendNotAuthorizedResponse(body, environ, start_response)

    def buildNotAuthorizedResponseBody(self, userName, path):
        return 'User \'%s\' is not authorized to access %s\n' % (userName, path)

    def buildMustAuthenticateBody(self, path):
        return 'Must authenticate to access %s\n' % path

    def sendNotAuthorizedResponse(self, body, environ, start_response):
        _logger.debug('401 Not Authorized (token)')
        wwwauthheaders = 'Token'

        body = compat.to_bytes(body)
        start_response('401 Not Authorized', [('WWW-Authenticate', wwwauthheaders),
                                              ('Content-Type', 'text/html'),
                                              ('Content-Length', str(len(body))),
                                              ('Date', util.getRfc1123Time()),
                                              ])
        return [body]

