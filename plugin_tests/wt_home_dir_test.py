#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
from tests import base
from girder import config
from girder.constants import ROOT_DIR
from girder.models.assetstore import Assetstore
from girder.models.token import Token

os.environ['GIRDER_PORT'] = os.environ.get('GIRDER_PORT', '30001')
config.loadConfig()  # Reload config to pick up correct port


def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.enabledPlugins.append('wt_home_dir')
    base.startServer(mock=False)


def tearDownModule():
    base.stopServer()


class IntegrationTestCase(base.TestCase):
    def setUp(self):
        base.TestCase.setUp(self)
        # We need to recreate DirectFS assetstore, which was dropped in
        # base.TestCase.setUp...
        assetstoreName = os.environ.get('GIRDER_TEST_ASSETSTORE', 'test')
        self.assetstorePath = os.path.join(
            ROOT_DIR, 'tests', 'assetstore', assetstoreName)
        self.assetstore = Assetstore().createDirectFSAssetstore(
            'WT Home Dirs', self.assetstorePath)

        # girder.plugins is not available until setUp is running
        global PluginSettings
        from girder.plugins.wt_home_dir import HOME_DIRS_APPS
        for e in HOME_DIRS_APPS.entries():
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

    def tearDown(self):
        base.TestCase.tearDown(self)

    def physicalPath(self, userName, path):
        return '%s/%s/%s/%s' % (self.assetstorePath, userName[0], userName, path)

    def testHomeDir(self):
        from webdavfs.webdavfs import WebDAVFS
        token = Token().createToken(self.user)
        resp = self.request(
            path='/resource/lookup', method='GET', user=self.user,
            params={'path': '/user/{login}/Home/ala'.format(**self.user)})
        url = 'http://127.0.0.1:%s' % os.environ['GIRDER_PORT']
        root = '/homes/{login}'.format(**self.user)
        password = 'token:{_id}'.format(**token)
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
