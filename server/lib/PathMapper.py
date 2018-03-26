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

    def addPrefix(self, s: pathlib.PurePosixPath, n) -> pathlib.PurePosixPath:
        if s.is_absolute():
            if len(s.parts) == 1:
                raise Exception('Invalid argument')
            prefix = s.parts[1]
        else:
            prefix = s.parts[0]

        assert len(prefix) != 0
        if len(prefix) > n:
            prefix = prefix[0:n]

        if s.is_absolute():
            return pathlib.PurePosixPath('/', prefix, *s.parts[1:])
        else:
            return pathlib.PurePosixPath(prefix, *s.parts)

    def getSubdir(self, environ: dict):
        raise Exception('Not implemented')

    def girderPathMatches(self, path: pathlib.Path):
        raise Exception('Not implemented')

    def getRealm(self):
        raise Exception('Not implemented')
    def isGirderRoot(self, path: pathlib.Path):
        raise NotImplementedError()


class HomePathMapper(PathMapper):
    def __init__(self):
        PathMapper.__init__(self)

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
        return len(path.parts) >= 4 and path.parts[1] == 'user' and path.parts[3] == 'Home'

    def getRealm(self):
        return 'homes'

    def isGirderRoot(self, path: pathlib.Path):
        # assume it already matches
        return len(path.parts) == 4


class TalePathMapper(PathMapper):
    def __init__(self):
        PathMapper.__init__(self)

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
        return len(path.parts) >= 4 and path.parts[1] == 'tale' and path.parts[3] == WORKSPACE_NAME

    def getRealm(self):
        return 'tales'

    def isGirderRoot(self, path: pathlib.Path):
        return len(path.parts) == 4
