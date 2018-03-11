import pathlib
from girder.plugins.wholetale.constants import WORKSPACE_NAME

class PathMapper:
    def __init__(self):
        pass

    def girderToDav(self, path: pathlib.Path):
        raise Exception('Not implemented')

    def davToGirder(self, path: str):
        raise Exception('Not implemented')

    def davToPhysical(self, path: str):
        raise Exception('Not implemented')

    def girderToPhysical(self, path: pathlib.Path):
        return self.davToPhysical(self.girderToDav(path))

    def addPrefix(self, s: str, n):
        if len(s) == 0:
            raise Exception('Invalid argument')
        if s[0] == '/':
            return '/%s/%s' % (s[1:n+1], s[1:])
        else:
            return '%s/%s' % (s[0:n], s)

    def getSubdir(self, environ: dict):
        raise Exception('Not implemented')

    def girderPathMatches(self, path: pathlib.Path):
        raise Exception('Not implemented')

    def getRealm(self):
        raise Exception('Not implemented')


class HomePathMapper(PathMapper):

    def __init__(self):
        pass

    def girderToDav(self, path: pathlib.Path):
        # /user/<username>/Home/<path> -> /<username>/<path>
        return '/%s/%s' % (path.parts[2], '/'.join(path.parts[4:]))

    def davToGirder(self, spath: str):
        path = pathlib.Path(spath)
        return '/user/%s/Home/%s' % (path.parts[1], '/'.join(path.parts[2:]).rstrip('/'))

    def davToPhysical(self, path: str):
        return self.addPrefix(path, 1)

    def getSubdir(self, environ: dict):
        return self.addPrefix(environ['WT_DAV_AUTHORIZED_USER'], 1)

    def girderPathMatches(self, path: pathlib.Path):
        return len(path.parts) > 4 and path.parts[1] == 'user' and path.parts[3] == 'Home'

    def getRealm(self):
        return 'homes'

class TalePathMapper(PathMapper):

    def __init__(self):
        pass

    def girderToDav(self, path: pathlib.Path):
        # /tale/<taleName>/<WORKSPACE_NAME>/... -> /...
        return '/%s/%s' % (path.parts[2], '/'.join(path.parts[4:]))

    def davToGirder(self, spath: str):
        path = pathlib.Path(spath)
        return '/tale/%s/%s/%s' % \
               (path.parts[1], WORKSPACE_NAME, '/'.join(path.parts[2:]).rstrip('/'))

    def davToPhysical(self, path: str):
        return self.addPrefix(path, 2)

    def getSubdir(self, environ: dict):
        return self.addPrefix(environ['WT_DAV_TALE'], 2)

    def girderPathMatches(self, path: pathlib.Path):
        # we may want to allow removal of the whole thing, and, maybe also in the case of users
        return len(path.parts) > 4 and path.parts[1] == 'tale' and path.parts[3] == WORKSPACE_NAME

    def getRealm(self):
        return 'tales'