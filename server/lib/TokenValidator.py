from wsgidav.middleware import BaseMiddleware
from girder.api.rest import *

# Some of the dict-like objects in cherrypy don't implement pop()
def safeDelAttr(dict, key):
    if hasattr(dict, key):
        delattr(dict, key)

class TokenValidator(BaseMiddleware):
    def __init__(self, application, config):
        BaseMiddleware.__init__(self, application, config)
        self.application = application
        self.config = config

    def __call__(self, environ, start_response):
        # The request object seems to be recycled accross connections
        safeDelAttr(cherrypy.request, 'girderUser')
        safeDelAttr(cherrypy.request, 'girderToken')
        # There seem to be many ways of passing stuff around.
        if 'HTTP_GIRDER_TOKEN' in environ:
            cherrypy.request.headers['Girder-Token'] = environ['HTTP_GIRDER_TOKEN']
        else:
            cherrypy.request.headers.pop('Girder-Token', None)
        user = getCurrentUser()
        if user is not None:
            environ['TOKEN_USER'] = user
        else:
            # no token; let HTTPAuthenticator deal with the situation
            pass
        return self.application(environ, start_response)