from wsgidav.middleware import BaseMiddleware
import os


class DirectoryInitializer(BaseMiddleware):
    def __init__(self, application, config):
        BaseMiddleware.__init__(self, application, config)
        self.application = application
        self.config = config
        self.initializedFor = {}

    def __call__(self, environ, start_response):
        userName = environ['WT_DAV_AUTHORIZED_USER']
        if userName not in self.initializedFor:
            root = self.config['wt_home_dirs_root']
            if root is None:
                raise EnvironmentError('wt_home_dirs_root not in config')
            os.makedirs('/%s/%s' % (root, userName), exist_ok=True)
            self.initializedFor[userName] = True
        return self.application(environ, start_response)
