#!/usr/bin/env python

import os
import pathlib
import stat
import shutil

from girder.models.upload import Upload
from girder.models.item import Item
from girder.models.folder import Folder
from girder.utility import mkdir
from girder.utility import path as path_lib
from girder.utility import hash_state
from girder.utility.filesystem_assetstore_adapter import FilesystemAssetstoreAdapter
from .PathMapper import PathMapper, HomePathMapper, TalePathMapper


# Default permissions for the files written to the filesystem
DEFAULT_PERMS = stat.S_IRUSR | stat.S_IWUSR


class WTAssetstoreAdapter(FilesystemAssetstoreAdapter):
    def __init__(self, assetstore, pathMapper: PathMapper):
        FilesystemAssetstoreAdapter.__init__(self, assetstore)
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
        os.remove(abspath)

    def fullPath(self, file):
        return self._getAbsPath(file['itemId'], 'item', None)


class WTHomeAssetstoreAdapter(WTAssetstoreAdapter):
    def __init__(self, assetstore):
        WTAssetstoreAdapter.__init__(self, assetstore, HomePathMapper())


class WTTaleAssetstoreAdapter(WTAssetstoreAdapter):
    def __init__(self, assetstore):
        WTAssetstoreAdapter.__init__(self, assetstore, TalePathMapper())
