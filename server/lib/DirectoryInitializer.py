from wsgidav.middleware import BaseMiddleware
import os
from .PathMapper import HomePathMapper, TalePathMapper


class DirectoryInitializer(BaseMiddleware):
    def __init__(self, application, config, pathMapper):
        BaseMiddleware.__init__(self, application, config)
        self.application = application
        self.config = config
        self.pathMapper = pathMapper
        self.initializedFor = {}

    def __call__(self, environ, start_response):
        # subdir is the user/tale specific part of the directory
        subdir = self.pathMapper.getSubdir(environ)
        if subdir not in self.initializedFor:
            root = self.config['wt_home_dirs_root']
            if root is None:
                raise EnvironmentError('wt_home_dirs_root not in config')
            path = '/%s/%s' % (root, subdir)
            os.makedirs(path, exist_ok=True)
            self.initializedFor[subdir] = True
        # use a multi-level path such that we don't end up with a large number of
        # entries in a single directory.
        # Specifically, use <firstLetterOfUsername>/<username> for homedir
        # and <firstTwoLettersOfTaleId>/<taleId> for tales
        # This means that we need to translate the logical path (e.g. /homes/<username>/<file>)
        # to the concrete path (e.g. /homes/<username>[0]/username/<file>) at some point,
        # and, since this is the last WT specific filter in the flow, as well as the
        # first filter to be aware of the mapping, do it here
        return self.application(environ, start_response)


class HomeDirectoryInitializer(DirectoryInitializer):
    def __init__(self, application, config):
        DirectoryInitializer.__init__(self, application, config, HomePathMapper())


class TaleDirectoryInitializer(DirectoryInitializer):
    def __init__(self, application, config):
        DirectoryInitializer.__init__(self, application, config, TalePathMapper())
