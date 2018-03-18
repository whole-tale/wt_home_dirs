import os
import stat

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

    def _refToGirderPath(self):
        return self.pathMapper.davToGirder(self.getRefUrl())

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
        try:
            folder = path_util.lookUpPath(self._refToGirderPath(), force=True)
            Folder().createFolder(
                parent=folder['document'], name=name, parentType='folder',
                creator=self.getUser())
        except ResourcePathNotFound:
            pass  # TODO: do something about it?
        FolderResource.createCollection(self, name)

    def createEmptyResource(self, name):
        logger.debug('%s -> createEmptyResource(%s)' % (self.getRefUrl(), name))
        try:
            folder = path_util.lookUpPath(self._refToGirderPath(), force=True)
            Item().createItem(
                folder=folder['document'], name=name,
                creator=self.getUser())
        except ResourcePathNotFound:
            pass  # TODO: do something about it?
        return FolderResource.createEmptyResource(self, name)

    def delete(self):
        try:
            folder = path_util.lookUpPath(self._refToGirderPath(), force=True)
            Folder().remove(folder['document'])
        except ResourcePathNotFound:
            # delete folder if it exists, since we won't get a notification from Girder in
            # this case
            self._delete()
        # Don't remove the folder here. Girder will post an event whose handler will
        # call _delete(), unless, of course, that fails
        # self._delete()

    # girder bypass
    def _delete(self):
        FolderResource.delete(self)


class WTFileResource(_WTDAVResource, FileResource):
    def __init__(self, path, environ, fp, pathMapper):
        FileResource.__init__(self, path, environ, fp)
        _WTDAVResource.__init__(self, pathMapper)

    def delete(self):
        try:
            item = path_util.lookUpPath(self._refToGirderPath(), force=True)
            Item().remove(item['document'])
        except ResourcePathNotFound:
            pass  # TODO: do something about it?

        if os.path.isfile(self._filePath):
            FileResource.delete(self)
        else:
            self.removeAllProperties(True)
            self.removeAllLocks(True)

    def endWrite(self, withErrors):
        FileResource.endWrite(self, withErrors)
        try:
            item = path_util.lookUpPath(self._refToGirderPath(), force=True)
            item = item.pop('document')

            FSProvider = self.environ['wsgidav.provider']
            # WTFileResource already has file stat object but it's stale,
            # we need a new one
            stat = os.stat(self._filePath)

            file = File().createFile(
                name=self.name, creator=self.getUser(), item=item, reuseExisting=True,
                size=stat.st_size, assetstore=FSProvider.assetstore,
                saveFile=False)
            file['path'] = self._filePath
            file['mtime'] = stat.st_mtime
            # file['imported'] = True
            File().save(file)
        except ResourcePathNotFound:
            pass  # TODO: do something about it?


# Adds support for 'executable' property
class WTFilesystemProvider(FilesystemProvider):
    def __init__(self, rootDir, pathMapper: PathMapper, assetstoreType: int):
        FilesystemProvider.__init__(self, rootDir)
        self.pathMapper = pathMapper
        self.assetstoreType = assetstoreType
        self.assetstore = None
        # must do this after setting the above
        self.updateAssetstore()

    def updateAssetstore(self):
        assetstore = [
            _ for _ in Assetstore().list()
            if _.get('root', '').rstrip('/') == self.rootFolderPath and self.isProperAssetstore(_)
        ]
        if not assetstore:
            assetstore = self.createAssetstore()
        else:
            assetstore = assetstore.pop()
        self.assetstore = assetstore

    def isProperAssetstore(self, assetstore):
        return assetstore['type'] in WTAssetstoreTypes.ALL

    def createAssetstore(self):
        logger.info('Creating assetstore %d' % self.assetstoreType)
        dict = {
            'type': self.assetstoreType,
            'created': datetime.datetime.utcnow(),
            'name': self.pathMapper.getRealm() + ' wtassetstore',
            'root': self.rootFolderPath,
            'perms': None
        }
        return Assetstore().save(dict)

    def getAssetstore(self):
        return self.assetstore

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
        return FilesystemProvider._locToFilePath(self, self.pathMapper.davToPhysical(path), environ)
