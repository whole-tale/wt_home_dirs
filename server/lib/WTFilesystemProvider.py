import os
import stat
import pathlib

import datetime
from wsgidav.fs_dav_provider import \
    FilesystemProvider, FolderResource, FileResource
from wsgidav import compat, util
from girder import logger
from girder.utility import path as path_util
from girder.exceptions import ResourcePathNotFound
from girder.models.assetstore import Assetstore
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.item import Item
from .PathMapper import PathMapper
from .WTAssetstoreTypes import WTAssetstoreTypes


PROP_EXECUTABLE = '{http://apache.org/dav/props/}executable'
WT_HOME_FLAG = '__WT_HOME__'


# A mixin to deal with the executable property for WT*Resource
class _WTDAVResource:
    def __init__(self, pathMapper):
        self.pathMapper = pathMapper

    def getPropertyNames(self, isAllProp):
        props = super().getPropertyNames(isAllProp)
        props.append(PROP_EXECUTABLE)
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

    def getUser(self):
        return self.environ['WT_DAV_USER_DICT']


class WTFolderResource(_WTDAVResource, FolderResource):
    def __init__(self, path, environ, fp, pathMapper):
        FolderResource.__init__(self, path, environ, fp)
        _WTDAVResource.__init__(self, pathMapper)

    # Override to return proper objects when doing recursive listings.
    # One would have thought that FilesystemProvider.getResourceInst() was
    # the only place that needed to be overriden...
    def getMember(self, name):
        assert compat.is_native(name), "%r" % name
        fp = os.path.join(self._filePath, compat.to_unicode(name))
        path = util.joinUri(self.path, name)
        if os.path.isdir(fp):
            res = WTFolderResource(path, self.environ, fp, self.pathMapper)
        elif os.path.isfile(fp):
            res = WTFileResource(path, self.environ, fp, self.pathMapper)
        else:
            res = None
        return res

    def createCollection(self, name):
        logger.debug('%s -> createCollection(%s)' % (self.getRefUrl(), name))
        FolderResource.createCollection(self, name)

    def createEmptyResource(self, name):
        logger.debug('%s -> createEmptyResource(%s)' % (self.getRefUrl(), name))
        return FolderResource.createEmptyResource(self, name)


class WTFileResource(_WTDAVResource, FileResource):
    def __init__(self, path, environ, fp, pathMapper):
        FileResource.__init__(self, path, environ, fp)
        _WTDAVResource.__init__(self, pathMapper)

    def delete(self):
        if os.path.isfile(self._filePath):
            FileResource.delete(self)
        else:
            self.removeAllProperties(True)
            self.removeAllLocks(True)


# Adds support for 'executable' property
class WTFilesystemProvider(FilesystemProvider):
    def __init__(self, rootDir, pathMapper: PathMapper):
        FilesystemProvider.__init__(self, rootDir)
        self.pathMapper = pathMapper

    def getResourceInst(self, path, environ):
        """Return info dictionary for path.

        See DAVProvider.getResourceInst()
        """
        self._count_getResourceInst += 1
        fp = self._locToFilePath(path, environ)
        if not os.path.exists(fp):
            return None

        if os.path.isdir(fp):
            return WTFolderResource(path, environ, fp, self.pathMapper)
        return WTFileResource(path, environ, fp, self.pathMapper)

    def _locToFilePath(self, path, environ=None):
        return FilesystemProvider._locToFilePath(self, self.pathMapper.davToPhysical(path),
                                                 environ)
