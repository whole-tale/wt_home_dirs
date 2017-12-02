from wsgidav.fs_dav_provider import FilesystemProvider, FolderResource, FileResource
from wsgidav import compat, util
import os
import stat


PROP_EXECUTABLE = '{http://apache.org/dav/props/}executable'
# A mixin to deal with the executable property for WT*Resource
class _WTDAVResource:
    def getPropertyNames(self, isAllProp):
        props = super().getPropertyNames(isAllProp)
        props.append(PROP_EXECUTABLE)
        print('%s: %s' % (self._filePath, props))
        return props

    def getPropertyValue(self, propname):
        if propname == PROP_EXECUTABLE:
            return self.isExecutable()
        else:
            return super().getPropertyValue(propname)

    def setPropertyValue(self, propname, value, dryRun=False):
        if propname == PROP_EXECUTABLE:
            if not dryRun:
                self.setExecutable(value)
        else:
            super().setPropertyValue(propname, value, dryRun)

    def isExecutable(self):
        if self.filestat[stat.ST_MODE] & stat.S_IEXEC == 0:
            return 'F'
        else:
            return 'T'

    def setExecutable(self, value):
        if value.text == '1' or value.text == 'T':
            newmode = self.filestat[stat.ST_MODE] | stat.S_IEXEC
        else:
            newmode = self.filestat[stat.ST_MODE] & (~stat.S_IEXEC)
        os.chmod(self._filePath, newmode)
        # re-read stat
        self.filestat = os.stat(self._filePath)

class WTFolderResource(_WTDAVResource, FolderResource):
    def __init__(self, path, environ, fp):
        FolderResource.__init__(self, path, environ, fp)

    # Override to return proper objects when doing recursive listings.
    # One would have thought that FilesystemProvider.getResourceInst() was
    # the only place that needed to be overriden...
    def getMember(self, name):
        assert compat.is_native(name), "%r" % name
        fp = os.path.join(self._filePath, compat.to_unicode(name))
        path = util.joinUri(self.path, name)
        if os.path.isdir(fp):
            res = WTFolderResource(path, self.environ, fp)
        elif os.path.isfile(fp):
            res = WTFileResource(path, self.environ, fp)
        else:
            res = None
        return res

class WTFileResource(_WTDAVResource, FileResource):
    def __init__(self, path, environ, fp):
        FileResource.__init__(self, path, environ, fp)

# Adds support for 'executable' property
class WTFilesystemProvider(FilesystemProvider):
    def __init__(self, rootDir):
        FilesystemProvider.__init__(self, rootDir)

    def getResourceInst(self, path, environ):
        """Return info dictionary for path.

        See DAVProvider.getResourceInst()
        """
        self._count_getResourceInst += 1
        fp = self._locToFilePath(path, environ)
        if not os.path.exists(fp):
            return None

        if os.path.isdir(fp):
            return WTFolderResource(path, environ, fp)
        return WTFileResource(path, environ, fp)