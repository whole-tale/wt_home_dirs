#!/usr/bin/env python

import os
import pathlib
import six
import datetime
import stat
import shutil
import contextlib

from girder.models.item import Item
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.assetstore import Assetstore
from girder.models.upload import Upload
from girder.models.user import User
from girder.utility import \
    mkdir, hash_state, RequestBodyStream, \
    assetstore_utilities
from girder.utility import path as path_lib
from girder.utility.filesystem_assetstore_adapter import FilesystemAssetstoreAdapter
from .PathMapper import PathMapper, HomePathMapper, TalePathMapper


# Default permissions for the files written to the filesystem
DEFAULT_PERMS = stat.S_IRUSR | stat.S_IWUSR


class WTAssetstoreAdapter(FilesystemAssetstoreAdapter):
    def __init__(self, assetstore, pathMapper: PathMapper):
        super(WTAssetstoreAdapter, self).__init__(assetstore)
        self.pathMapper = pathMapper

    def _getAbsPath(self, parentId, parentType, name):
        if parentType == 'folder':
            parent = Folder().load(id=parentId, force=True)
        else:
            parent = Item().load(id=parentId, force=True)
        fullPath = path_lib.getResourcePath(parentType, parent, force=True)
        if name is not None:
            fullPath = pathlib.Path(os.path.join(fullPath, name))
        path = self.pathMapper.girderToPhysical(fullPath)
        # relativize this path
        path = os.path.relpath(path, '/')
        return os.path.join(self.assetstore['root'], path)

    """
    This assetstore type stores files on the filesystem underneath a root
    directory.

    :param assetstore: The assetstore to act on.
    :type assetstore: dict
    """

    def finalizeUpload(self, upload, file):
        """
        Moves the file into its permanent content-addressed location within the
        assetstore. Directory hierarchy yields 256^2 buckets.
        """
        hash = hash_state.restoreHex(
            upload['sha512state'], 'sha512').hexdigest()

        if 'fileId' in upload:
            file = File().load(upload['fileId'], force=True)
            abspath = self._getAbsPath(file['itemId'], 'item', file['name'])
            abspath = os.path.dirname(abspath)
        else:
            abspath = self._getAbsPath(upload['parentId'], upload['parentType'], upload['name'])

        absdir = os.path.dirname(abspath)

        # Store the hash in the upload so that deleting a file won't delete
        # this file
        if '_id' in upload:
            upload['sha512'] = hash
            Upload().update(
                {'_id': upload['_id']}, update={'$set': {'sha512': hash}})

        mkdir(absdir)

        # Move the temp file to permanent location in the assetstore.
        # shutil.move works across filesystems
        shutil.move(upload['tempFile'], abspath)
        try:
            os.chmod(abspath, self.assetstore.get('perms', DEFAULT_PERMS))
        except OSError:
            # some filesystems may not support POSIX permissions
            pass

        file['sha512'] = hash

        return file

    def deleteFile(self, file):
        # can't rely on 'path' since it's not updated properly on rename/move/copy.
        abspath = self._getAbsPath(file['itemId'], 'item', None)
        with contextlib.suppress(FileNotFoundError):
            os.remove(abspath)

    def fullPath(self, file):
        return self._getAbsPath(file['itemId'], 'item', None)

    def copyFile(self, srcFile, destFile):
        """
        This method copies the necessary fields and data so that the
        destination file contains the same data as the source file.
        If a destination File do not belong to WTAssetstore, a snapshot of
        the File content is made and is uploaded to the current assetstore.

        :param srcFile: The original File document.
        :type srcFile: dict
        :param destFile: The File which should have the data copied to it.
        :type destFile: dict
        :returns: A dict with the destination file.
        """
        destItem = Item().load(id=destFile['itemId'], force=True)
        destPath = path_lib.getResourcePath('item', destItem, force=True)
        destInWTHome = self.pathMapper.girderPathMatches(pathlib.Path(destPath))

        srcItem = Item().load(id=srcFile['itemId'], force=True)
        srcPath = path_lib.getResourcePath('item', srcItem, force=True)
        srcInWTHome = self.pathMapper.girderPathMatches(pathlib.Path(srcPath))

        if srcInWTHome and not destInWTHome:
            return self._copyFileFromWT(srcFile, destFile)
        else:
            return destFile

    def _copyFileFromWT(self, srcFile, destFile):
        # TODO: We assume that something other than WebDAV is the default
        assetstore = Assetstore().getCurrent()
        adapter = assetstore_utilities.getAssetstoreAdapter(assetstore)
        now = datetime.datetime.utcnow()
        user = User().load(destFile['creatorId'], force=True)
        destFile = File().save(destFile)  # we need Id

        upload = {
            'created': now,
            'updated': now,
            'userId': user['_id'],
            'fileId': destFile['_id'],
            'assetstoreId': assetstore['_id'],
            'size': int(srcFile['size']),
            'name': destFile['name'],
            'mimeType': destFile['mimeType'],
            'received': 0
        }
        upload = adapter.initUpload(upload)
        upload = Upload().save(upload)

        if srcFile['size'] == 0:
            return File().filter(Upload().finalizeUpload(upload), user)
        chunkSize = Upload()._getChunkSize()
        chunk = None
        for data in File().download(srcFile, headers=False)():
            if chunk is not None:
                chunk += data
            else:
                chunk = data
            if len(chunk) >= chunkSize:
                upload = Upload().handleChunk(upload, RequestBodyStream(six.BytesIO(chunk), len(chunk)))
                chunk = None

        if chunk is not None:
            upload = Upload().handleChunk(upload, RequestBodyStream(six.BytesIO(chunk), len(chunk)))
        destFile.update(upload)
        return destFile


class WTHomeAssetstoreAdapter(WTAssetstoreAdapter):
    def __init__(self, assetstore):
        WTAssetstoreAdapter.__init__(self, assetstore, HomePathMapper())


class WTTaleAssetstoreAdapter(WTAssetstoreAdapter):
    def __init__(self, assetstore):
        WTAssetstoreAdapter.__init__(self, assetstore, TalePathMapper())
