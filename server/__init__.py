#!/usr/bin/env python
# -*- coding: utf-8 -*-

import cherrypy
import os
import pathlib
from wsgidav.wsgidav_app import DEFAULT_CONFIG, WsgiDAVApp
from wsgidav.dir_browser import WsgiDavDirBrowser
from wsgidav.debug_filter import WsgiDavDebugFilter
from wsgidav.http_authenticator import HTTPAuthenticator
from wsgidav.error_printer import ErrorPrinter
from girder import events
from girder.constants import ROOT_DIR
from girder.models.setting import Setting
from girder.utility import setting_utilities
from girder.utility import path as path_util
from girder.constants import SettingDefault
from .constants import PluginSettings
from .lib.Authorizer import Authorizer
from .lib.DirectoryInitializer import DirectoryInitializer
from .lib.WTDomainController import WTDomainController
from .lib.WTFilesystemProvider import WTFilesystemProvider
from .resources.homedirpass import Homedirpass


HOME_DIRS_APP = None


@setting_utilities.validator({
    PluginSettings.HOME_DIRS_ROOT,
})
def validateOtherSettings(event):
    pass


def handleGirderFolderDelete(event):
    # Folders removed from Girder don't trigger Assetstore remove,
    # we need to handle it via events
    folder_path = path_util.getResourcePath('folder', event.info, force=True)
    path = pathlib.Path(folder_path)
    if len(path.parts) > 4 and (path.parts[1] == 'user' and
                                path.parts[3] == 'Home'):
        root_path = HOME_DIRS_APP.providerMap['/']['provider'].rootFolderPath
        folder = root_path + os.sep + path.parts[2] + os.sep
        folder += os.sep.join(path.parts[4:])
        if os.path.isdir(folder):
            os.rmdir(folder)


def load(info):
    events.bind('model.folder.remove', 'wt_home_dir', handleGirderFolderDelete)
    if 'GIRDER_TEST_ASSETSTORE' in os.environ:
        assetstoreName = os.environ.get('GIRDER_TEST_ASSETSTORE', 'test')
        assetstorePath = os.path.join(
            ROOT_DIR, 'tests', 'assetstore', assetstoreName)
        SettingDefault.defaults[PluginSettings.HOME_DIRS_ROOT] = assetstorePath
    else:
        SettingDefault.defaults[PluginSettings.HOME_DIRS_ROOT] = '/tmp/wt-home-dirs'

    settings = Setting()

    homeDirsRoot = settings.get(PluginSettings.HOME_DIRS_ROOT)

    if not os.path.exists(homeDirsRoot):
        os.makedirs(homeDirsRoot)

    provider = WTFilesystemProvider(homeDirsRoot)
    config = DEFAULT_CONFIG.copy()
    # Accept basic authentication and assume access through HTTPS only. This (HTTPS when only
    # basic is accepted) is enforced by some clients.
    # The reason for not accepting digest authentication is that it would require storage of
    # unsalted password hashes on the server. Maybe that's OK, since one could store
    # HA1 (md5(username:realm:password)) as specified by the digest auth RFC. But for now,
    # this seems simpler.
    config.update({
        'mount_path': '/homes',
        'wt_home_dirs_root': homeDirsRoot,
        'provider_mapping': {'/': provider},
        'user_mapping': {},
        'middleware_stack': [WsgiDavDirBrowser, DirectoryInitializer, Authorizer,
                             HTTPAuthenticator, ErrorPrinter, WsgiDavDebugFilter],
        'acceptbasic': True,
        'acceptdigest': False,
        'defaultdigest': False,
        'domaincontroller': WTDomainController(),
        'server': 'cherrypy'
    })
    global HOME_DIRS_APP
    HOME_DIRS_APP = WsgiDAVApp(config)
    cherrypy.tree.graft(HOME_DIRS_APP, '/homes')
    tree = cherrypy.tree
    print(tree)

    hdp = Homedirpass()
    info['apiRoot'].homedirpass = hdp
    info['apiRoot'].homedirpass.route('GET', ('generate',), hdp.generatePassword)
    info['apiRoot'].homedirpass.route('PUT', ('set',), hdp.setPassword)
