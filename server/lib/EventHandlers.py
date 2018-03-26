import os
import pathlib
from typing import Union
from wsgidav.dav_provider import DAVCollection
from girder.events import Event
from girder.utility import path as path_util
from girder.models.folder import Folder
from girder.models.item import Item
from . WTFilesystemProvider import WTFilesystemProvider, WT_HOME_FLAG


class EventHandler:
    def __init__(self):
        pass

    def getPath(self, event: Event):
        return path_util.getResourcePath(self.getResourceType(event), self.getResource(event),
                                         force=True)

    def getResourceType(self, event: Event):
        raise Exception('Not implemented')

    def getResource(self, event: Event):
        raise Exception('Not implemented')

    def getResourceInstance(self, girderPath: Union[pathlib.Path, str], pathMapper,
                            provider: WTFilesystemProvider):
        if isinstance(girderPath, str):
            girderPath = pathlib.Path(girderPath)
        return provider.getResourceInst(pathMapper.girderToDavStr(girderPath),
                                        {'wsgidav.provider': provider})

    def getPhysicalPath(self, girderPath, pathMapper, provider) -> str:
        return provider._locToFilePath(pathMapper.girderToDavStr(girderPath),
                                       {'wsgidav.provider': provider})

    def run(self, event: Event, path: pathlib.Path, pathMapper, provider: WTFilesystemProvider):
        raise Exception('Not implemented')

# Things we need to handle:
#   Folder:
#       - update: this is basically a move/rename operation, since it can involve both a name
#           change and re-parenting. The rename has to be done by intercepting the save event, since
#           there doesn't seem to be a specific event associated with resource/folder/updateFolder.
#           Unfortunately, there is also no event for folder.move, so that also has to be detected
#           using the save event by somehow keeping track of where the folder was, since the
#           event we get from the save event will not have the old parent id, so we really have
#           no idea where that folder was moved from unless we take a peak at the database to
#           see the parentId of the unsaved folder. Methinks we're compounding bad ideas here.
#
#       - updateFolderAccess: (maybe)
#       - create: of course, no specific event for this either from girder. So save is to be
#           used again. We have to distinguish between rename/move/create based on:
#               * does not have _id when we get model.folder.save -> create
#               * has _id when we get model.folder.save:
#                   * same parent as stored model with same _id -> rename
#                   * different parent ---''--- -> move (and possibly rename if name different)
#           the chance of this being maintainable/correct is pretty low
#       - copyFolder: this is a recursive folder.create and item.copyItem, the latter having
#           an event (model.item.copy.prepare(srcItem, dstItem))
#       - deleteContents: folder.remove + item.remove
#   Item: (as usual, we do have the problem of mapping the multiple-file-in-an-item model to a FS)
#       - update: like with folders, this is move/rename depending on parameters
#       - delete
#       - copyItem
#


class FolderDeleteHandler(EventHandler):
    def getResourceType(self, event: Event):
        return 'folder'

    def getResource(self, event: Event):
        return event.info

    def run(self, event: Event, path: pathlib.Path, pathMapper, provider: WTFilesystemProvider):
        # Folders removed from Girder don't trigger Assetstore remove,
        # we need to handle it via events

        res = self.getResourceInstance(path, pathMapper, provider)
        if res is not None and isinstance(res, DAVCollection):
            res._delete()


class FolderSaveHandler(EventHandler):
    def getResourceType(self, event: Event):
        return 'folder'

    def getResource(self, event: Event):
        return event.info

    def run(self, event: Event, path: pathlib.Path, pathMapper, provider: WTFilesystemProvider):
        folder = self.getResource(event)
        if folder['description'] == WT_HOME_FLAG:
            folder['description'] = ''
            return
        if pathMapper.isGirderRoot(path):
            return
        if '_id' not in folder:
            self.createFolder(path, pathMapper, provider)
        else:
            storedFolder = Folder().load(folder['_id'], force=True)
            if storedFolder['parentId'] != folder['parentId']:
                self.moveFolder(storedFolder, folder, pathMapper, provider)
            elif storedFolder['name'] != folder['name']:
                self.renameFolder(storedFolder, folder['name'], pathMapper, provider)
            else:
                # not something we care about
                pass

    def createFolder(self, path: pathlib.Path, pathMapper, provider: WTFilesystemProvider):
        # path: str
        path = self.getPhysicalPath(path, pathMapper, provider)
        os.makedirs(path)

    def assertIsValidFolder(self, res, path):
        if res is None:
            raise IOError('Specified folder does not exist: %s' % path)
        if not isinstance(res, DAVCollection):
            raise IOError('Specified resource is not a folder on disk: %s' % path)

    def moveFolder(self, src: dict, dst: dict, pathMapper, provider: WTFilesystemProvider):
        girderSrcPath = path_util.getResourcePath('folder', src, force=True)
        girderDstPath = path_util.getResourcePath('folder', dst, force=True)

        davDstPath = pathMapper.girderToDav(girderDstPath)

        res = self.getResourceInstance(girderSrcPath, pathMapper, provider)
        self.assertIsValidFolder(res, girderSrcPath)

        res.moveRecursive(davDstPath.as_posix())

    def renameFolder(self, src: dict, newName: str, pathMapper, provider: WTFilesystemProvider):
        girderSrcPath = path_util.getResourcePath('folder', src, force=True)
        res = self.getResourceInstance(girderSrcPath, pathMapper, provider)
        self.assertIsValidFolder(res, girderSrcPath)
        davPath = pathMapper.girderToDav(girderSrcPath)
        res.moveRecursive(davPath.parent.joinpath(newName).as_posix())


class ItemSaveHandler(EventHandler):
    def getResourceType(self, event: Event):
        return 'item'

    def getResource(self, event: Event):
        return event.info

    def run(self, event: Event, path: pathlib.Path, pathMapper, provider: WTFilesystemProvider):
        item = self.getResource(event)
        if item['description'] == WT_HOME_FLAG:
            item['description'] = ''
            return
        if '_id' in item:
            storedItem = Item().load(item['_id'], force=True)
            if storedItem['folderId'] != item['folderId']:
                self.moveItem(storedItem, item, pathMapper, provider)
            elif storedItem['name'] != item['name']:
                self.renameItem(storedItem, item['name'], pathMapper, provider)
            else:
                # not something we care about
                pass

    def assertIsValidFile(self, res, path):
        if res is None:
            raise IOError('Specified file does not exist: %s' % path)
        if isinstance(res, DAVCollection):
            raise IOError('Found a folder where a file was expected: %s' % path)

    def moveItem(self, src: dict, dst: dict, pathMapper, provider: WTFilesystemProvider):
        girderSrcPath = path_util.getResourcePath('item', src, force=True)
        girderDstPath = path_util.getResourcePath('item', dst, force=True)

        davDstPath = pathMapper.girderToDav(girderDstPath)

        res = self.getResourceInstance(girderSrcPath, pathMapper, provider)
        self.assertIsValidFile(res, girderSrcPath)

        res.moveRecursive(davDstPath.as_posix())

    def renameItem(self, src: dict, newName: str, pathMapper, provider: WTFilesystemProvider):
        girderSrcPath = path_util.getResourcePath('item', src, force=True)
        res = self.getResourceInstance(girderSrcPath, pathMapper, provider)
        davPath = pathMapper.girderToDav(girderSrcPath)
        self.assertIsValidFile(res, girderSrcPath)
        res.moveRecursive(davPath.parent.joinpath(newName).as_posix())


class AssetstoreQueryHandler(EventHandler):
    def getResourceType(self, event: Event):
        # it seems that the model and resource are the location where the upload happens
        # rather than the target upload item/file
        return 'folder'

    def getResource(self, event: Event):
        return event.info['resource']

    def run(self, event: Event, path: pathlib.Path, pathMapper, provider: WTFilesystemProvider):
        event.addResponse(provider.getAssetstore())
        event.stopPropagation()
