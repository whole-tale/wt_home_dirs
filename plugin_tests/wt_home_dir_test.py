#!/usr/bin/env python
# -*- coding: utf-8 -*-

from tests import base
from girder.models.token import Token
from girder import config
import os

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
            self.assertTrue(
                os.path.isdir(
                    '/tmp/wt-home-dirs/{login}/ala'.format(**self.user)))
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
            self.assertFalse(
                os.path.isdir(
                    '/tmp/wt-home-dirs/{login}/ala'.format(**self.user)))
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
