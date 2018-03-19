#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
from tests import base
from girder import config
from girder.constants import ROOT_DIR
from girder.models.assetstore import Assetstore
from girder.models.token import Token
from webdavfs.webdavfs import WebDAVFS

os.environ['GIRDER_PORT'] = os.environ.get('GIRDER_PORT', '30001')
config.loadConfig()  # Reload config to pick up correct port

def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.enabledPlugins.append('wt_home_dir')
    base.startServer(mock=False)


def tearDownModule():
    base.stopServer()


class Adapter:
    def __init__(self, realm, pathMapper, app, user: dict):
        self.realm = realm
        self.pathMapper = pathMapper
        self.app = app
        self.user = user
        self.userName = user['login']

    def mkdir(self, name):
        raise NotImplementedError()

    def rmdir(self, name):
        raise NotImplementedError()

    def isdir(self, name):
        raise NotImplementedError()

    def exists(self, name):
        raise NotImplementedError()

    def renamedir(self, src, dst):
        raise NotImplementedError()

    def mvdir(self, dir, dst):
        raise NotImplementedError()


class FSAdapter(Adapter):
    def __init__(self, realm, pathMapper, app, user: dict, clean=False):
        Adapter.__init__(self, realm, pathMapper, app, user)
        provider = app.providerMap['/']['provider']
        self.root = provider.rootFolderPath + '/' + pathMapper.davToPhysical(self.userName)

    def mkdir(self, name):
        # this one is read-only
        raise NotImplementedError()

    def rmdir(self, name):
        raise NotImplementedError()

    def isdir(self, name):
        return os.path.isdir(self.root + '/' + name)

    def exists(self, name):
        return os.path.exists(self.root + '/' + name)

    def renamedir(self, src, dst):
        raise NotImplementedError()

    def mvdir(self, dir, dst):
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

    def mkdir(self, path):
        self.handle.makedir(path)

    def rmdir(self, path):
        self.handle.removedir(path)

    def isdir(self, path):
        return self.handle.isdir(path)

    def exists(self, path):
        return self.handle.exists(path)

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
        self.handle.client.move(dir, dst)


class GirderAdapter(Adapter):
    def __init__(self, realm, pathMapper, app, user: dict, client, rootDir):
        Adapter.__init__(self, realm, pathMapper, app, user)
        self.client = client
        self.rootDir = rootDir
        resp = self.getResource(rootDir)
        self.rootId = resp.json['_id']

    def getResource(self, path, canFail=False):
        if canFail:
            return self.canFail(path='/resource/lookup', method='GET', user=self.user,
                                params={'path': path})
        else:
            return self.mustSucceed(path='/resource/lookup', method='GET', user=self.user,
                                    params={'path': path})

    def mustSucceed(self, path, method, user, params):
        resp = self.client.request(path=path, method=method, user=user, params=params)
        if not resp.status.startswith('200'):
            raise Exception('Request failed with status %s: %s' % (resp.status, resp.body))

        return resp

    def canFail(self, path, method, user, params):
        return self.client.request(path=path, method=method, user=user, params=params)

    def mkdir(self, name):
        self.mustSucceed(path='/folder', method='POST', user=self.user,
                         params={'parentId': self.rootId, 'name': name})

    def rmdir(self, name):
        resp = self.getResource('%s/%s' % (self.rootDir, name))
        if not resp.json['_modelType'] == 'folder':
            raise Exception('Not a folder: %s' % name)
        self.mustSucceed(path='/folder/%s' % resp.json['_id'], method='DELETE', user=self.user,
                         params=None)

    def isdir(self, name):
        resp = self.getResource('%s/%s' % (self.rootDir, name))
        return resp.json['_modelType'] == 'folder'

    def exists(self, name):
        resp = self.getResource('%s/%s' % (self.rootDir, name), canFail=True)
        return resp.status.startswith('200')

    def renamedir(self, src, dst):
        resp = self.getResource('%s/%s' % (self.rootDir, src))
        if not resp.json['_modelType'] == 'folder':
            raise Exception('Not a folder: %s' % src)
        self.mustSucceed(path='/folder/%s' % resp.json['_id'], method='PUT', user=self.user,
                         params={'name': dst})

    def mvdir(self, dir, dst):
        resp = self.getResource('%s/%s' % (self.rootDir, dir))
        if not resp.json['_modelType'] == 'folder':
            raise Exception('Not a folder: %s' % dir)
        srcId = resp.json['_id']
        resp = self.getResource('%s/%s' % (self.rootDir, dst))
        if not resp.json['_modelType'] == 'folder':
            raise Exception('Not a folder: %s' % dst)
        dstId = resp.json['_id']
        self.mustSucceed(path='/folder/%s' % srcId, method='PUT', user=self.user,
                         params={'parentType': 'folder', 'parentId': dstId})


# Tests:
#   - mkdir dav <-> girder
#   - rmdir dav <-> girder
#   - rename dir
#   - move dir
#   - same for files
#   - content check for files
#   * test for all apps


class IntegrationTestCase(base.TestCase):
    def setUp(self):
        base.TestCase.setUp(self)
        from girder.plugins.wt_home_dir import HOME_DIRS_APPS
        self.homeDirsApps = HOME_DIRS_APPS  # nopep8
        # We need to recreate DirectFS assetstore, which was dropped in
        # base.TestCase.setUp...
        assetstoreName = os.environ.get('GIRDER_TEST_ASSETSTORE', 'test')
        self.assetstorePath = os.path.join(
            ROOT_DIR, 'tests', 'assetstore', assetstoreName)

        # girder.plugins is not available until setUp is running
        for e in self.homeDirsApps.entries():
            e.app.providerMap['/']['provider'].updateAssetstore()

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
        self.clearDAVAuthCache()

    def clearDAVAuthCache(self):
        # need to do this because the DB is wiped on every test, but the dav domain
        # controller keeps a cache with users/tokens
        for e in self.homeDirsApps.entries():
            e.app.config['domaincontroller'].clearCache()

    def tearDown(self):
        base.TestCase.tearDown(self)

    def physicalPath(self, userName, path):
        return '%s/%s/%s/%s' % (self.assetstorePath, userName[0], userName, path)

    def forallapps(self, fn):
        print('Running %s' % fn.__name__)
        for e in self.homeDirsApps.entries():
            if e.realm == 'tales':
                print('Skipping tales realm since we don''t quite know how it works yet')
                return
            self.makeAdapters(e.realm, e.pathMapper, e.app, self.user)
            fn()

    def checkRealm(self, realm):
        if realm not in ['homes', 'tales']:
            raise KeyError('Don''t know how to handle realm %s' % realm)

    def getDAVRootDir(self, realm):
        self.checkRealm(realm)
        if realm == 'homes':
            return self.user['login']
        elif realm == 'tales':
            return self.taleId

    def getGirderRootDir(self, realm):
        self.checkRealm(realm)
        if realm == 'homes':
            return '/user/%s/Home' % self.user['login']
        elif realm == 'tales':
            return '/tale/%s/Workspace' % self.taleId

    def makeAdapters(self, realm, pathMapper, app, user: dict):
        self.davAdapter = DAVAdapter(realm, pathMapper, app, user, self.token,
                                     self.getDAVRootDir(realm))
        self.girderAdapter = GirderAdapter(realm, pathMapper, app, user, self,
                                           self.getGirderRootDir(realm))
        self.fsAdapter = FSAdapter(realm, pathMapper, app, user, clean=True)

    # make directory with one adapter and check that it exists with all of them
    def mkdir(self, mainAdapter, name):
        print('mkdir(%s)' % name)
        mainAdapter.mkdir(name)
        self.ensureIsDir(name)

    def ensureExists(self, name):
        print('ensureExists(%s)' % name)
        self.assertTrue(self.davAdapter.exists(name))
        self.assertTrue(self.girderAdapter.exists(name))
        self.assertTrue(self.fsAdapter.exists(name))

    def ensureIsDir(self, name):
        print('ensureIsDir(%s)' % name)
        self.assertTrue(self.davAdapter.isdir(name))
        self.assertTrue(self.girderAdapter.isdir(name))
        self.assertTrue(self.fsAdapter.isdir(name))

    def rmdir(self, mainAdapter, name):
        mainAdapter.rmdir(name)
        self.ensureNotExists(name)

    def ensureNotExists(self, name):
        print('ensureNotExists(%s)' % name)
        self.assertFalse(self.davAdapter.exists(name))
        self.assertFalse(self.girderAdapter.exists(name))
        self.assertFalse(self.fsAdapter.exists(name))

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
        # TODO: well, the dav -> girder link isn't implemented o this one
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
        self._testFolderMove(self.girderAdapter, 'testdir8', 'testdir9', 'testdir10')

    def _testFolderMove(self, adapter, dir1, dir2, dir3):
        self.mkdir(adapter, dir1)
        self.mkdir(adapter, dir1 + '/' + dir2)
        self.mkdir(adapter, dir3)
        adapter.mvdir(dir1 + '/' + dir2, dir3)
        self.ensureIsDir(dir3 + '/' + dir1)
        self.ensureNotExists(dir1 + '/' + dir2)
        self.rmdir(dir1)
        self.rmdir(dir3 + '/' + dir1)
        self.rmdir(dir3)

    def test07Files(self):
        self.forallapps(self._testFiles)

    def _testFiles(self):
        pass

    def test08HomeDir(self):
        resp = self.request(
            path='/resource/lookup', method='GET', user=self.user,
            params={'path': '/user/{login}/Home/ala'.format(**self.user)})
        url = 'http://127.0.0.1:%s' % os.environ['GIRDER_PORT']
        root = '/homes/{login}'.format(**self.user)
        password = 'token:{_id}'.format(**self.token)
        with WebDAVFS(url, login=self.user['login'], password=password,
                      root=root) as handle:
            self.assertEqual(handle.listdir('.'), [])
            handle.makedir('ala')
            # exists in WebDAV
            self.assertEqual(handle.listdir('.'), ['ala'])
            # exists on the backend
            physDirPath = self.physicalPath(self.user['login'], 'ala')
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

        with WebDAVFS(url, login=self.user['login'], password=password,
                      root=root) as handle:
            self.assertEqual(handle.listdir('.'), [])
            handle.makedir('test_dir')

            with handle.open('test_dir/test_file.txt', 'w') as fp:
                fsize = fp.write('Hello world!')

            self.assertEqual(handle.listdir('.'), ['test_dir'])
            self.assertEqual(handle.listdir('test_dir'), ['test_file.txt'])
            fAbsPath = self.physicalPath(self.user['login'], 'test_dir/test_file.txt')
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
