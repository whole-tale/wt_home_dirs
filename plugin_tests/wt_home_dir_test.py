#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import time
from bson.objectid import ObjectId
from tests import base
from girder import config
from girder.constants import TokenScope
from girder.models.api_key import ApiKey
from girder.models.token import Token
from girder.utility.model_importer import ModelImporter
from webdavfs.webdavfs import WebDAVFS

os.environ['GIRDER_PORT'] = os.environ.get('GIRDER_PORT', '30001')
config.loadConfig()  # Reload config to pick up correct port

FILE_CONTENTS = ''.join(['0123456789abcdefghijklmnopqrstuvxyz' for i in range(10)])


def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.enabledPlugins.append('wt_home_dir')
    base.enabledPlugins.append('virtual_resources')
    base.startServer(mock=False)


def tearDownModule():
    base.stopServer()


# why I didn't go with FS and a simple layer on top, I'm not sure
class Adapter:
    def __init__(self, realm, pathMapper, app, user: dict):
        self.realm = realm
        self.pathMapper = pathMapper
        self.app = app
        self.user = user
        self.userName = user['login']
        self.name = '-'

    def mkdir(self, path):
        raise NotImplementedError()

    def rmdir(self, path):
        raise NotImplementedError()

    def isdir(self, path):
        raise NotImplementedError()

    def isfile(self, path):
        raise NotImplementedError()

    def exists(self, path):
        raise NotImplementedError()

    def size(self, path):
        raise NotImplementedError()

    def renamedir(self, src, dst):
        raise NotImplementedError()

    def mvdir(self, dir, dst):
        raise NotImplementedError()

    def mvfile(self, src, dst):
        raise NotImplementedError()

    def mkfile(self, path, data):
        raise NotImplementedError()

    def getfile(self, path):
        raise NotImplementedError()

    def rm(self, path):
        raise NotImplementedError()

    def renamefile(self, src, dst):
        raise NotImplementedError()


class FSAdapter(Adapter):
    def __init__(self, realm, pathMapper, app, user: dict, rootDir: str):
        Adapter.__init__(self, realm, pathMapper, app, user)
        provider = app.providerMap['/']['provider']
        self.root = provider.rootFolderPath + '/' + pathMapper.davToPhysical(rootDir)
        self.name = 'FS'

    def mkdir(self, path):
        # this one is read-only
        raise NotImplementedError()

    def rmdir(self, path):
        raise NotImplementedError()

    def isdir(self, path):
        return os.path.isdir(self.root + '/' + path)

    def isfile(self, path):
        return os.path.isfile(self.root + '/' + path)

    def exists(self, path):
        return os.path.exists(self.root + '/' + path)

    def size(self, path):
        return os.path.getsize(self.root + '/' + path)

    def renamedir(self, src, dst):
        raise NotImplementedError()

    def mvdir(self, dir, dst):
        raise NotImplementedError()

    def mvfile(self, src, dst):
        raise NotImplementedError()

    def mkfile(self, path, data):
        raise NotImplementedError()

    def getfile(self, path):
        with open(self.root + '/' + path) as f:
            return f.read()

    def rm(self, path):
        os.remove(self.root + '/' + path)

    def renamefile(self, src, dst):
        raise NotImplementedError()


class DAVAdapter(Adapter):
    def __init__(self, realm, pathMapper, app, user: dict, token, realmDir):
        Adapter.__init__(self, realm, pathMapper, app, user)
        url = 'http://127.0.0.1:%s' % os.environ['GIRDER_PORT']
        password = 'token:%s' % token['_id']
        self.root = '/%s/%s' % (realm, realmDir)
        self.handle = WebDAVFS(url, login=self.userName, password=password, root=self.root)
        self.handle.makedir('test')
        if not self.handle.isdir('test'):
            raise Exception('Basic DAV test failed')
        self.handle.removedir('test')
        self.name = 'DAV'

    def mkdir(self, path):
        self.handle.makedir(path)

    def rmdir(self, path):
        self.handle.removedir(path)

    def isdir(self, path):
        return self.handle.isdir(path)

    def isfile(self, path):
        return self.handle.isfile(path)

    def exists(self, path):
        return self.handle.exists(path)

    def size(self, path):
        return self.handle.getsize(path)

    def renamedir(self, src, dst):
        # see mvdir
        src = self.handle.validatepath(src)
        dst = self.handle.validatepath(dst)
        self.handle.client.move(src, dst)

    def mvdir(self, dir, dst):
        # WebDAVFS is being silly. Doesn't allow you to move directories (move requires
        # the source to be a file, while movedir is not implemented, so it defaults to
        # whatever FS does). Anyway, bypass it.
        dir = self.handle.validatepath(dir)
        dst = self.handle.validatepath(dst)
        # handle.client.move() does not check reply for errors!
        self.handle.client.move(dir, dst)

    def mvfile(self, src, dst):
        self.handle.move(src, dst, overwrite=False)

    def mkfile(self, path, data):
        with self.handle.open(path, 'w') as fp:
            fsize = fp.write(data)
            if fsize != len(data):
                raise Exception('Could not write all data to DAV file')

    def getfile(self, path):
        with self.handle.open(path) as f:
            return f.read()

    def rm(self, path):
        self.handle.remove(path)

    def renamefile(self, src, dst):
        self.handle.move(src, dst, overwrite=False)


class GirderAdapter(Adapter):
    def __init__(self, realm, pathMapper, app, user: dict, client, rootDir):
        Adapter.__init__(self, realm, pathMapper, app, user)
        self.client = client
        self.rootDir = rootDir
        resp = self.getResource(rootDir)
        self.rootId = resp.json['_id']
        self.name = 'Girder'

    def getResource(self, path, canFail=False):
        if canFail:
            return self.canFail(path='/resource/lookup', method='GET', user=self.user,
                                params={'path': path})
        else:
            return self.mustSucceed(path='/resource/lookup', method='GET', user=self.user,
                                    params={'path': path})

    def mustSucceed(self, path, method, user, params=None, isJson=True, body=None):
        resp = self.client.request(path=path, method=method, user=user, params=params,
                                   isJson=isJson, body=body)
        if not resp.status.startswith('200'):
            raise Exception('Request failed with status %s: %s' % (resp.status, resp.body))

        return resp

    def canFail(self, path, method, user, params):
        return self.client.request(path=path, method=method, user=user, params=params)

    def getFolder(self, path):
        # Is the trailing slash an unreasonable assumption? Works in most other places
        path = ('%s/%s' % (self.rootDir, path)).rstrip('/')
        resp = self.getResource(path)
        if not resp.json['_modelType'] == 'folder':
            raise Exception('Not a folder: %s' % path)
        return resp

    def getFile(self, path):
        resp = self.getResource('%s/%s' % (self.rootDir, path))
        if not resp.json['_modelType'] == 'item':
            raise Exception('Not an item: %s' % path)
        return resp

    def mkdir(self, path):
        parentPath = os.path.dirname(path)
        name = os.path.basename(path)
        # this method assumes parent exists
        resp = self.getFolder(parentPath)
        self.mustSucceed(path='/folder', method='POST', user=self.user,
                         params={'parentId': resp.json['_id'], 'name': name})

    def rmdir(self, path):
        resp = self.getFolder(path)
        self.mustSucceed(path='/folder/%s' % resp.json['_id'], method='DELETE', user=self.user,
                         params=None)

    def isdir(self, path):
        resp = self.getResource('%s/%s' % (self.rootDir, path))
        return resp.json['_modelType'] == 'folder'

    def isfile(self, path):
        resp = self.getResource('%s/%s' % (self.rootDir, path))
        return resp.json['_modelType'] == 'item'

    def exists(self, path):
        resp = self.getResource('%s/%s' % (self.rootDir, path), canFail=True)
        return resp.status.startswith('200')

    def size(self, path):
        resp = self.getResource('%s/%s' % (self.rootDir, path), canFail=True)
        if not resp.status.startswith('200'):
            raise Exception('Could not get resource for %s' % path)
        return resp.json['size']

    def renamedir(self, src, dst):
        resp = self.getFolder(src)
        self.mustSucceed(path='/folder/%s' % resp.json['_id'], method='PUT', user=self.user,
                         params={'name': dst})

    def mvdir(self, dir, dst):
        # must convert from "unified" semantics of "dir becomes dst" to girder semantics
        # of dir gets moved into dirname(dst)
        print('girder.mvdir(%s, %s)' % (dir, dst))
        resp = self.getFolder(dir)
        srcId = resp.json['_id']
        dstDir = os.path.dirname(dst)
        newName = os.path.basename(dst)
        resp = self.getFolder(dstDir)
        dstId = resp.json['_id']
        self.mustSucceed(path='/folder/%s' % srcId, method='PUT', user=self.user,
                         params={'name': newName, 'parentType': 'folder', 'parentId': dstId})

    def mvfile(self, src, dst):
        print('girder.mvfile(%s, %s)' % (src, dst))
        resp = self.getFile(src)
        srcId = resp.json['_id']
        dstDir = os.path.dirname(dst)
        newName = os.path.basename(dst)
        resp = self.getFolder(dstDir)
        dstId = resp.json['_id']
        self.mustSucceed(path='/item/%s' % srcId, method='PUT', user=self.user,
                         params={'name': newName, 'folderId': dstId})

    def _upload_file(self, name, contents, user, parent, parentType="folder",
                     mimeType=None):
        """
        Upload a file. This is meant for small testing files, not very large
        files that should be sent in multiple chunks.

        :param name: The name of the file.
        :type name: str
        :param contents: The file contents
        :type contents: str
        :param user: The user performing the upload.
        :type user: dict
        :param parent: The parent document.
        :type parent: dict
        :param parentType: The type of the parent ("folder" or "item")
        :type parentType: str
        :param mimeType: Explicit MIME type to set on the file.
        :type mimeType: str
        :returns: The file that was created.
        :rtype: dict
        """
        mimeType = mimeType or 'application/octet-stream'
        resp = self.client.request(
            path='/file', method='POST', user=user, params={
                'parentType': parentType,
                'parentId': str(parent['_id']),
                'name': name,
                'size': len(contents),
                'mimeType': mimeType
            })
        self.client.assertStatusOk(resp)

        fields = [('offset', 0), ('uploadId', resp.json['_id'])]
        files = [('chunk', name, contents)]
        resp = self.client.multipartRequest(
            path='/file/chunk', user=user, fields=fields, files=files)
        self.client.assertStatusOk(resp)

        _file = resp.json
        self.client.assertHasKeys(_file, ['itemId'])
        self.client.assertEqual(_file['name'], name)
        self.client.assertEqual(_file['size'], len(contents))
        self.client.assertEqual(_file['mimeType'], mimeType)

        return _file

    def mkfile(self, path, data):
        parentPath = os.path.dirname(path)
        parent = self.getFolder(parentPath)
        name = os.path.basename(path)
        resp = self._upload_file(name, data, user=self.user, parent=parent.json,
                                 parentType='folder')
        if '_id' not in resp:
            raise Exception('Request failed with response %s' % resp)

    def getfile(self, path):
        resp = self.getFile(path)
        resp = self.mustSucceed(path='/item/%s/download' % resp.json['_id'], method='GET',
                                user=self.user,
                                params={'contentDisposition': 'inline'}, isJson=False)
        s = ''
        for chunk in resp.body:
            s = s + chunk.decode('utf8')
        return s

    def rm(self, path):
        resp = self.getFile(path)
        self.mustSucceed(path='/item/%s' % resp.json['_id'], method='DELETE', user=self.user)

    def renamefile(self, src, dst):
        resp = self.getFile(src)
        self.mustSucceed(path='/item/%s' % resp.json['_id'], method='PUT', user=self.user,
                         params={'name': dst})


# Tests:
#   - mkdir dav <-> girder
#   - rmdir dav <-> girder
#   - rename dir
#   - move dir
#   - same for files
#   - content check for files
#   * test for all apps
#   TODO: test recursive copy/move
#   TODO: write tests which check that Alice can't mess with Bob's files


class IntegrationTestCase(base.TestCase):
    def setUp(self):
        base.TestCase.setUp(self)
        from girder.plugins.wt_home_dir import HOME_DIRS_APPS
        self.homeDirsApps = HOME_DIRS_APPS  # nopep8
        from girder.plugins.wt_home_dir.constants import WORKSPACE_NAME
        global WORKSPACE_NAME
        # We need to recreate DirectFS assetstore, which was dropped in
        # base.TestCase.setUp...

        # girder.plugins is not available until setUp is running
        for e in self.homeDirsApps.entries():
            provider = e.app.providerMap['/']['provider']
            if e.realm == 'homes':
                self.homesRoot = provider.rootFolderPath
                self.homesPathMapper = e.pathMapper

        users = ({
            'email': 'root@dev.null',
            'login': 'admin',
            'firstName': 'Root',
            'lastName': 'van Klompf',
            'password': 'secret'
        }, {
            'email': 'joe@dev.null',
            'login': 'joeregular',
            'firstName': 'Joe',
            'lastName': 'Regular',
            'password': 'secret'
        })
        self.admin, self.user = [self.model('user').createUser(**user)
                                 for user in users]
        self.token = Token().createToken(self.user)
        self.api_key = ApiKey().createApiKey(
            user=self.user, name="webdav", scope=[TokenScope.DATA_OWN]
        )

        self.privateTale = self.createTale(self.user, public=False)
        # TODO: add tests checking that other users only have read access to public tales
        self.publicTale = self.createTale(self.admin, public=True)
        self.clearDAVAuthCache()

    def createTale(self, user, public):
        # fake a recipe because the model downloads actual stuff
        recipe = {'_id': ObjectId()}
        imageModel = ModelImporter.model('image', 'wholetale')
        image = imageModel.createImage(recipe, 'test image', creator=user, public=public)
        taleModel = ModelImporter.model('tale', 'wholetale')
        return taleModel.createTale(image, [], creator=user, public=public)

    def clearDAVAuthCache(self):
        # need to do this because the DB is wiped on every test, but the dav domain
        # controller keeps a cache with users/tokens
        for e in self.homeDirsApps.entries():
            e.app.config['domaincontroller'].clearCache()

    def tearDown(self):
        base.TestCase.tearDown(self)

    def homesPhysicalPath(self, userName, path):
        return '%s/%s' % (self.homesRoot,
                          self.homesPathMapper.davToPhysical('%s/%s' % (userName, path)))

    def forallapps(self, fn):
        print('Running %s' % fn.__name__)
        for e in self.homeDirsApps.entries():
            if e.realm == 'tales':
                self.makeTaleAdapters(e.pathMapper, e.app, self.user)
                continue
            elif e.realm == 'homes':
                self.makeHomeAdapters(e.pathMapper, e.app, self.user)
            else:
                raise Exception('Unknonw realm %s' % e.realm)
            fn()

    def checkRealm(self, realm):
        if realm not in ['homes', 'tales']:
            raise KeyError('Don''t know how to handle realm %s' % realm)

    def makeHomeAdapters(self, pathMapper, app, user: dict):
        userName = self.user['login']
        davRootDir = userName
        girderRootDir = '/user/%s/Home' % userName
        fsRootDir = userName

        self.makeAdapters('homes', pathMapper, app, user, davRootDir, girderRootDir, fsRootDir)

    def makeTaleAdapters(self, pathMapper, app, user: dict):
        taleId = str(self.privateTale['_id'])
        davRootDir = taleId
        girderRootDir = '/collection/%s/%s/%s' % (WORKSPACE_NAME, WORKSPACE_NAME, taleId)
        fsRootDir = taleId

        self.makeAdapters('tales', pathMapper, app, user, davRootDir, girderRootDir, fsRootDir)

    def makeAdapters(self, realm, pathMapper, app, user, davRootDir, girderRootDir, fsRootDir):
        self.davAdapter = DAVAdapter(realm, pathMapper, app, user, self.token, davRootDir)
        self.girderAdapter = GirderAdapter(realm, pathMapper, app, user, self, girderRootDir)
        self.fsAdapter = FSAdapter(realm, pathMapper, app, user, fsRootDir)

        self.allAdapters = [self.davAdapter, self.girderAdapter, self.fsAdapter]

    # make directory with one adapter and check that it exists with all of them
    def mkdir(self, mainAdapter, name):
        print('mkdir(%s)' % name)
        mainAdapter.mkdir(name)
        self.ensureIsDir(name)

    def mkfile(self, mainAdapter, name, data):
        print('mkfile(%s)' % name)
        mainAdapter.mkfile(name, data)
        self.ensureIsFile(name, len(data))
        self.ensureFileContentEqualTo(name, data)

    def rm(self, mainAdapter, name):
        print('rm(%s)' % name)
        mainAdapter.rm(name)
        self.ensureNotExists(name)

    def ensureExists(self, name):
        print('ensureExists(%s)' % name)
        for adapter in self.allAdapters:
            self.assertTrue(adapter.exists(name))

    def ensureIsDir(self, name):
        print('ensureIsDir(%s)' % name)
        for adapter in self.allAdapters:
            self.assertTrue(adapter.isdir(name), msg='Not a directory %s' % name)

    def ensureIsFile(self, name, size=None):
        print('ensureIsFile(%s)' % name)
        for adapter in self.allAdapters:
            self.assertTrue(adapter.isfile(name), msg='(%s) Not a file %s' % (adapter.name, name))
            if size:
                self.assertEqual(adapter.size(name), size, msg='File size for %s differs' % name)

    def ensureFileContentEqualTo(self, name, data):
        for adapter in self.allAdapters:
            self.assertEqual(adapter.getfile(name), data, msg='File content differs')

    def rmdir(self, mainAdapter, name):
        mainAdapter.rmdir(name)
        self.ensureNotExists(name)

    def ensureNotExists(self, name):
        print('ensureNotExists(%s)' % name)
        for adapter in self.allAdapters:
            self.assertFalse(adapter.exists(name),
                             msg='(%s) File should not exist: %s' % (adapter.name, name))

    def test00FolderCreateRemoveDav(self):
        self.forallapps(self._testFolderCreateRemoveDav)

    def _testFolderCreateRemoveDav(self):
        self._testFolderCreateRemove(self.davAdapter, 'testdir')

    def test01FolderCreateRemoveGirder(self):
        self.forallapps(self._testFolderCreateRemoveGirder)

    def _testFolderCreateRemoveGirder(self):
        self._testFolderCreateRemove(self.girderAdapter, 'testdir2')

    def _testFolderCreateRemove(self, adapter, name):
        self.mkdir(adapter, name)
        self.rmdir(adapter, name)

    def test02DeepFolders(self):
        self.forallapps(self._testDeepFolders)

    def _testDeepFolders(self):
        path = 'td1'
        paths = []
        for depth in range(1, 10):
            paths.append(path)
            self.mkdir(self.davAdapter, path)
            path = '%s/td%d' % (path, depth)

        for path in reversed(paths):
            self.rmdir(self.davAdapter, path)

    def test03FolderRenameDav(self):
        self.forallapps(self._testFolderRenameDav)

    def _testFolderRenameDav(self):
        self._testFolderRename(self.davAdapter, 'testdir4', 'testdir5')

    def _testFolderRename(self, adapter, src, dst):
        self.mkdir(adapter, src)
        adapter.renamedir(src, dst)
        self.ensureIsDir(dst)
        self.ensureNotExists(src)
        self.rmdir(adapter, dst)

    def test04FolderRenameGirder(self):
        self.forallapps(self._testFolderRenameGirder)

    def _testFolderRenameGirder(self):
        self._testFolderRename(self.girderAdapter, 'testdir6', 'testdir7')

    def test05FolderMoveDav(self):
        self.forallapps(self._testFolderMoveDav)

    def _testFolderMoveDav(self):
        self._testFolderMove(self.davAdapter, 'testdir8', 'testdir9', 'testdir10')

    def test06FolderMoveGirder(self):
        self.forallapps(self._testFolderMoveGirder)

    def _testFolderMoveGirder(self):
        self._testFolderMove(self.girderAdapter, 'testdir11', 'testdir12', 'testdir13')

    def _testFolderMove(self, adapter, dir1, dir2, dir3):
        self.mkdir(adapter, dir1)
        self.mkdir(adapter, dir1 + '/' + dir2)
        self.mkdir(adapter, dir3)
        # semantics here for webdav are src becomes dest, not src is moved into dest
        adapter.mvdir(dir1 + '/' + dir2, dir3 + '/' + dir2)
        self.ensureIsDir(dir3 + '/' + dir2)
        self.ensureNotExists(dir1 + '/' + dir2)
        self.rmdir(adapter, dir1)
        self.rmdir(adapter, dir3 + '/' + dir2)
        self.rmdir(adapter, dir3)

    def test07FileCreateRemoveDav(self):
        self.forallapps(self._testFileCreateRemoveDav)

    def _testFileCreateRemoveDav(self):
        self._testFileCreateRemove(self.davAdapter, 'testfile1.txt')

    def test08FileCreateRemoveGirder(self):
        self.forallapps(self._testFileCreateRemoveGirder)

    def _testFileCreateRemoveGirder(self):
        self._testFileCreateRemove(self.girderAdapter, 'testfile2.txt')

    def _testFileCreateRemove(self, adapter, name):
        self.mkfile(adapter, name, FILE_CONTENTS)
        self.rm(adapter, name)

    def test09FileRenameDav(self):
        self.forallapps(self._testFileRenameDav)

    def _testFileRenameDav(self):
        self._testFileRename(self.davAdapter, 'testfile3.txt', 'testfile4.txt')

    def _testFileRename(self, adapter, src, dst):
        self.mkfile(adapter, src, FILE_CONTENTS)
        adapter.renamefile(src, dst)
        self.ensureIsFile(dst)
        self.ensureNotExists(src)
        self.rm(adapter, dst)

    def test10FileRenameGirder(self):
        self.forallapps(self._testFileRenameGirder)

    def _testFileRenameGirder(self):
        self._testFileRename(self.girderAdapter, 'testfile6.txt', 'testfile7.txt')

    def test11FileMoveDav(self):
        self.forallapps(self._testFileMoveDav)

    def _testFileMoveDav(self):
        self._testFileMove(self.davAdapter, 'testdirf1', 'testfile8.txt', 'testdirf2')

    def test12FileMoveGirder(self):
        self.forallapps(self._testFileMoveGirder)

    def _testFileMoveGirder(self):
        self._testFileMove(self.girderAdapter, 'testdirf3', 'testfile9.txt', 'testdirf4')

    def _testFileMove(self, adapter, dir1, file2, dir3):
        self.mkdir(adapter, dir1)
        self.mkfile(adapter, dir1 + '/' + file2, FILE_CONTENTS)
        self.mkdir(adapter, dir3)
        # semantics here for webdav are src becomes dest, not src is moved into dest
        adapter.mvfile(dir1 + '/' + file2, dir3 + '/' + file2)
        self.ensureIsFile(dir3 + '/' + file2)
        self.ensureNotExists(dir1 + '/' + file2)
        self.rmdir(adapter, dir1)
        self.rm(adapter, dir3 + '/' + file2)
        self.rmdir(adapter, dir3)

    def test13HomeDir(self):
        resp = self.request(
            path='/resource/lookup', method='GET', user=self.user,
            params={'path': '/user/{login}/Home/ala'.format(**self.user)})
        url = 'http://127.0.0.1:%s' % os.environ['GIRDER_PORT']
        root = '/homes/{login}'.format(**self.user)
        password = 'token:{_id}'.format(**self.token)
        time.sleep(1)
        with WebDAVFS(url, login=self.user['login'], password=password,
                      root=root) as handle:
            self.assertEqual(handle.listdir('.'), [])
            handle.makedir('ala')
            # exists in WebDAV
            self.assertEqual(handle.listdir('.'), ['ala'])
            # exists on the backend
            physDirPath = self.homesPhysicalPath(self.user['login'], 'ala')
            self.assertTrue(os.path.isdir(physDirPath))
            # exists in Girder
            resp = self.request(
                path='/resource/lookup', method='GET', user=self.user,
                params={'path': '/user/{login}/Home/ala'.format(**self.user)})
            self.assertStatusOk(resp)
            self.assertEqual(resp.json['_modelType'], 'folder')
            self.assertEqual(resp.json['name'], 'ala')

            handle.removedir('ala')
            # gone from WebDAV
            self.assertEqual(handle.listdir('.'), [])
            # gone from the backend
            self.assertFalse(os.path.isdir(physDirPath))
            # gone from Girder
            resp = self.request(
                path='/resource/lookup', method='GET', user=self.user,
                params={'path': '/user/{login}/Home/ala'.format(**self.user)})
            self.assertStatus(resp, 400)
            self.assertEqual(resp.json, {
                'type': 'validation',
                'message': ('Path not found: '
                            'user/{login}/Home/ala'.format(**self.user))
            })

        with WebDAVFS(
            url, login=self.user['login'], password=f"key:{self.api_key['key']}", root=root
        ) as handle:
            self.assertEqual(handle.listdir('.'), [])
            handle.makedir('test_dir')

            with handle.open('test_dir/test_file.txt', 'w') as fp:
                fsize = fp.write('Hello world!')

            self.assertEqual(handle.listdir('.'), ['test_dir'])
            self.assertEqual(handle.listdir('test_dir'), ['test_file.txt'])
            fAbsPath = self.homesPhysicalPath(self.user['login'], 'test_dir/test_file.txt')
            fAbsPathCopy = self.homesPhysicalPath(
                self.user['login'], 'test_dir/test_file.txt (1)')
            self.assertTrue(os.path.isfile(fAbsPath))

            gabspath = '/user/{login}/Home/test_dir/test_file.txt'
            resp = self.request(
                path='/resource/lookup', method='GET', user=self.user,
                params={'path': gabspath.format(**self.user)})

            self.assertStatusOk(resp)
            self.assertEqual(resp.json['_modelType'], 'item')
            self.assertEqual(resp.json['name'], 'test_file.txt')
            self.assertEqual(resp.json['size'], fsize)

            item = resp.json
            resp = self.request(
                path='/item/{_id}/files'.format(**item), method='GET',
                user=self.user)
            self.assertStatusOk(resp)
            self.assertEqual(len(resp.json), 1)
            gfile = resp.json[0]
            self.assertEqual(gfile['size'], fsize)

            resp = self.request(
                path='/item/{_id}/download'.format(**item), method='GET',
                user=self.user, params={'contentDisposition': 'inline'},
                isJson=False)
            self.assertStatusOk(resp)
            with open(fAbsPath, 'r') as fp:
                self.assertEqual(self.getBody(resp), fp.read())

            resp = self.request(
                path='/resource/copy', method='POST', user=self.user,
                params={
                    'resources': '{"item": ["%s"]}' % item['_id'],
                    'parentType': 'folder',
                    'parentId': item['folderId'],
                    'progress': False
                }
            )
            self.assertStatusOk(resp)
            self.assertTrue(os.path.isfile(fAbsPathCopy))

            gabspath = '/user/{login}/Home/test_dir/test_file.txt (1)'
            resp = self.request(
                path='/resource/lookup', method='GET', user=self.user,
                params={'path': gabspath.format(**self.user)})
            self.assertStatusOk(resp)
            self.assertEqual(resp.json['_modelType'], 'item')
            self.assertEqual(resp.json['name'], 'test_file.txt (1)')
            self.assertEqual(resp.json['size'], fsize)
            resp = self.request(
                path='/item/{_id}'.format(**resp.json), method='DELETE',
                user=self.user)
            self.assertStatusOk(resp)
            self.assertFalse(os.path.isfile(fAbsPathCopy))

            resp = self.request(
                path='/item/{_id}'.format(**item), method='DELETE',
                user=self.user)
            self.assertStatusOk(resp)
            self.assertFalse(os.path.isfile(fAbsPath))

            fAbsPath = os.path.dirname(fAbsPath)
            self.assertTrue(os.path.isdir(fAbsPath))

            resp = self.request(
                path='/folder/{folderId}'.format(**item), method='DELETE',
                user=self.user)
            self.assertStatusOk(resp)
            self.assertFalse(os.path.isdir(fAbsPath))
