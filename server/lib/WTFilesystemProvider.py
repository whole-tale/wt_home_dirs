import os
import stat
import pathlib
from wsgidav.fs_dav_provider import \
    FilesystemProvider, FolderResource, FileResource
from wsgidav import compat, util
from girder.utility import path as path_util
from girder.exceptions import ResourcePathNotFound
from girder.models.assetstore import Assetstore
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.item import Item


PROP_EXECUTABLE = '{http://apache.org/dav/props/}executable'


# A mixin to deal with the executable property for WT*Resource
class _WTDAVResource:
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
        path = pathlib.Path(self.getRefUrl())
        return '/user/{}/Home/{}'.format(
            path.parts[1], os.sep.join(path.parts[2:])).rstrip(os.sep)
    def getUser(self):
        return self.environ['WT_DAV_USER_DICT']


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
            pass  # TODO: do something about it?
        FolderResource.delete(self)


class WTFileResource(_WTDAVResource, FileResource):
    def __init__(self, path, environ, fp):
        FileResource.__init__(self, path, environ, fp)

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
            file['path'] = FSProvider.rootFolderPath + self.path
            file['mtime'] = stat.st_mtime
            # file['imported'] = True
            File().save(file)
        except ResourcePathNotFound:
            pass  # TODO: do something about it?


# Adds support for 'executable' property
class WTFilesystemProvider(FilesystemProvider):
    def __init__(self, rootDir):
        FilesystemProvider.__init__(self, rootDir)
        self.updateAssetstore()

    def updateAssetstore(self):
        assetstore = [
            _ for _ in Assetstore().list()
            if _.get('root', '').rstrip('/') == self.rootFolderPath
        ]
        if not assetstore:
            assetstore = Assetstore().createDirectFSAssetstore(
                'WT Home Dirs', self.rootFolderPath)
        else:
            assetstore = assetstore.pop()
        self.assetstore = assetstore

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
