from wsgidav.middleware import BaseMiddleware
from wsgidav import compat, util
from girder.utility.model_importer import ModelImporter
from girder.constants import AccessType
from girder.exceptions import AccessException, ValidationException
import pathlib

_logger = util.getModuleLogger(__name__, True)

DAV_READ_OPS = set(['HEAD', 'GET', 'PROPFIND', 'OPTIONS'])


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

        return self._checkAccess(userName, path, environ, start_response)

    def _checkAccess(self, userName, path, environ, start_response):
        pass

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


class HomeAuthorizer(Authorizer):
    def __init__(self, application, config):
        Authorizer.__init__(self, application, config)

    def _checkAccess(self, userName, path, environ, start_response):
        # allow /<userName> and /<userName>/*
        # should probably check that login names don't allow things like '../../etc'
        if path == ('/%s' % userName) or path.startswith('/%s/' % userName):
            return self.application(environ, start_response)
        else:
            body = self.buildNotAuthorizedResponseBody(userName, path)
            return self.sendNotAuthorizedResponse(body, environ, start_response)


class TaleAuthorizer(Authorizer):
    def __init__(self, application, config):
        Authorizer.__init__(self, application, config)
        self.taleModel = ModelImporter.model('tale', 'wholetale')

    def _checkAccess(self, userName, spath: str, environ, start_response):
        # allow access to /<tale> and /<tale>/* if:
        #   it's a write op and user has admin access on tale
        #   it's a read op and user has read access on tale
        # otherwise, deny access

        path = pathlib.Path(spath)

        if len(path.parts) < 2:
            body = self.buildNotAuthorizedResponseBody(userName, path)
            return self.sendNotAuthorizedResponse(body, environ, start_response)

        taleId = self.getTaleId(path)
        user = environ['WT_DAV_USER_DICT']

        if self.isReadOp(environ):
            access_level = AccessType.READ
        else:
            access_level = AccessType.ADMIN

        try:
            tale = self.taleModel.load(taleId, user=user, level=access_level, exc=True)
        except (AccessException, ValidationException):
            body = self.buildNotAuthorizedResponseBody(userName, path)
            return self.sendNotAuthorizedResponse(body, environ, start_response)

        environ['WT_DAV_TALE_DICT'] = tale
        environ['WT_DAV_TALE_ID'] = taleId
        return self.application(environ, start_response)

    def getTaleId(self, path: pathlib.Path):
        return path.parts[1]

    def isReadOp(self, environ):
        return environ['REQUEST_METHOD'] in DAV_READ_OPS
