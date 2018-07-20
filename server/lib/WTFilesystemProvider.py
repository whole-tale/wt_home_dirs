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

    def _refToGirderPath(self):
        return self.pathMapper.davToGirder(self.provider.sharePath + self.getPreferredPath())

    def getUser(self):
        return self.environ['WT_DAV_USER_DICT']

    def _girderLookup(self, path):
        # ensure that the path does not end in a slash since lookUpPath fails if that's the
        # case.
        path = path.rstrip('/')
        r = path_util.lookUpPath(path, filter=False, force=True)
        doc = r['document']
        doc['_modelType'] = r['model']
        return doc

    def _girderMkdir(self, parentDoc, name):
        # avoid recursive dav -> girder -> dav folder creation by passing a flag
        # in the description to prevent the event handler from creating the same folder
        Folder().createFolder(
            parent=parentDoc, name=name, description=WT_HOME_FLAG,
            parentType=parentDoc['_modelType'], creator=self.getUser())

    def _girderMkdirs(self, girderPath: pathlib.Path, origPath: pathlib.Path):
        if len(girderPath.parts) == 1:
            raise Exception('Cannot create folder %s' % origPath.as_posix())
        # there are more efficient ways to do this, but they are not necessarily more portable
        try:
            return self._girderLookup(girderPath.as_posix())
        except ResourcePathNotFound:
            parentDoc = self._girderMkdirs(girderPath.parent, origPath)
            self._girderMkdir(parentDoc, girderPath.name)

    def _girderMoveOrRename(self, dest):
        selfPath = pathlib.PurePosixPath(self.path)
        destPath = pathlib.PurePosixPath(dest)

        if selfPath.parent == destPath.parent or len(destPath.parts) == 1:
            self._girderRename(destPath.name)
        else:
            self._girderMove(dest)

    def _girderRename(self, newName: str):
        doc = self._girderLookup(self._refToGirderPath())
        doc['name'] = newName
        doc['description'] = WT_HOME_FLAG
        self._girderUpdateModel(doc)

    def _girderUpdateModel(self, doc):
        raise NotImplementedError()

    def _girderCopy(self, destPath):
        doc = self._girderLookup(self._refToGirderPath())
        # the assumption in FolderResource.copyMoveSingle seems to be that the parent
        # of destPath must exist
        destGirderParentPath = self.pathMapper.davToGirder(os.path.dirname(destPath))
        girderDestDoc = self._girderLookup(destGirderParentPath)
        self._girderModelCopy(doc, girderDestDoc, destPath)

    def _girderModelCopy(self, doc, destDoc, destPath):
        raise NotImplementedError()

    def _girderMove(self, destPath: str):
        doc = self._girderLookup(self._refToGirderPath())
        # FolderResource.moveRecursive asserts that destPath does not exist
        destGirderParentPath = self.pathMapper.davToGirder(os.path.dirname(destPath))
        dest = pathlib.Path(destGirderParentPath)
        self._girderMkdirs(dest, dest)
        girderDestDoc = self._girderLookup(destGirderParentPath)
        doc['description'] = WT_HOME_FLAG
        self._girderModelMove(doc, girderDestDoc)

    def _girderModelMove(self, doc, destDoc):
        raise NotImplementedError()


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
        try:
            folderDoc = self._girderLookup(self._refToGirderPath())
            self._girderMkdir(folderDoc, name)
        except ResourcePathNotFound:
            pass  # TODO: do something about it?

    def createEmptyResource(self, name):
        logger.debug('%s -> createEmptyResource(%s)' % (self.getRefUrl(), name))
        try:
            folderDoc = self._girderLookup(self._refToGirderPath())
            Item().createItem(folder=folderDoc, name=name, creator=self.getUser())
        except ResourcePathNotFound:
            pass  # TODO: do something about it?
        return FolderResource.createEmptyResource(self, name)

    def delete(self):
        try:
            folderDoc = self._girderLookup(self._refToGirderPath())
            Folder().remove(folderDoc)
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

    def copyMoveSingle(self, destPath, isMove):
        FolderResource.copyMoveSingle(self, destPath, isMove)
        # looking at the FolderResource.copyMoveSingle implementation, it looks like
        # this isn't actually implementing a move. The isMove parameter is only used
        # to figure out whether to copy or move the properties. Until such time that
        # we understand why any FS operation would map to a move of the properties
        # without deleting the source, we'll stick to copying the properties
        self._girderCopy(destPath)

    def moveRecursive(self, destPath):
        FolderResource.moveRecursive(self, destPath)
        self._girderMoveOrRename(destPath)

    def _girderUpdateModel(self, doc):
        Folder().updateFolder(doc)

    def _girderModelCopy(self, srcDoc, destDoc, destPath):
        Folder().copyFolder(srcFolder=srcDoc, parent=destDoc,
                            name=os.path.basename(destPath), description=WT_HOME_FLAG,
                            parentType=destDoc['_modelType'],
                            public=srcDoc['public'], creator=self.getUser())

    def _girderModelMove(self, doc, destDoc):
        Folder().move(doc, parent=destDoc, parentType=destDoc['_modelType'])


class WTFileResource(_WTDAVResource, FileResource):
    def __init__(self, path, environ, fp, pathMapper):
        FileResource.__init__(self, path, environ, fp)
        _WTDAVResource.__init__(self, pathMapper)

    def delete(self):
        try:
            item = self._girderLookup(self._refToGirderPath())
            Item().remove(item)
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
            itemDoc = self._girderLookup(self._refToGirderPath())

            FSProvider = self.environ['wsgidav.provider']
            # WTFileResource already has file stat object but it's stale,
            # we need a new one
            stat = os.stat(self._filePath)

            file = File().createFile(
                name=self.name, creator=self.getUser(), item=itemDoc, reuseExisting=True,
                size=stat.st_size, assetstore=FSProvider.assetstore, saveFile=False)
            file['path'] = self._filePath
            file['mtime'] = stat.st_mtime
            file['description'] = WT_HOME_FLAG
            # file['imported'] = True
            File().save(file)
        except ResourcePathNotFound:
            pass  # TODO: do something about it?

    def copyMoveSingle(self, destPath, isMove):
        FileResource.copyMoveSingle(self, destPath, isMove)
        self._girderCopy(destPath)

    def _girderCopyFolder(self, destPath):
        itemDoc = self._girderLookup(self._refToGirderPath())
        destGirderParentPath = self.pathMapper.davToGirder(os.path.dirname(destPath))
        girderDestDoc = self._girderLookup(destGirderParentPath)
        item = Item().copyItem(
            srcItem=itemDoc, creator=self.getUser(), name=os.path.basename(destPath),
            folder=girderDestDoc, description=WT_HOME_FLAG)
        self._unifyName(item)

    def moveRecursive(self, destPath):
        FileResource.moveRecursive(self, destPath)
        self._girderMoveOrRename(destPath)

    def _unifyName(self, item):
        for file in Item().childFiles(item=item):
            file['name'] = item['name']
            File().updateFile(file)

    def _girderUpdateModel(self, doc):
        item = Item().updateItem(doc)
        self._unifyName(item)

    def _girderModelCopy(self, srcDoc, destDoc, destPath):
        item = Item().copyItem(
            srcItem=srcDoc, creator=self.getUser(), parent=destDoc,
            name=os.path.basename(destPath), description=WT_HOME_FLAG)
        self._unifyName(item)

    def _girderModelMove(self, doc, destDoc):
        item = Item().move(doc, destDoc)
        self._unifyName(item)


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
        logger.debug('Creating or updating assetstore %d' % self.assetstoreType)
        name = self.pathMapper.getRealm() + ' wtassetstore'
        assetstore = Assetstore().findOne(query={'name': name})
        if not assetstore:
            assetstore = {
                'type': self.assetstoreType,
                'created': datetime.datetime.utcnow(),
                'name': name,
                'perms': None
            }
        assetstore['root'] = self.rootFolderPath
        return Assetstore().save(assetstore)

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
        return FilesystemProvider._locToFilePath(self, self.pathMapper.davToPhysical(path),
                                                 environ)
