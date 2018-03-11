#!/usr/bin/env python
# -*- coding: utf-8 -*-

import cherrypy
from wsgidav.wsgidav_app import DEFAULT_CONFIG, WsgiDAVApp
from wsgidav.dir_browser import WsgiDavDirBrowser
from wsgidav.debug_filter import WsgiDavDebugFilter
from wsgidav.http_authenticator import HTTPAuthenticator
from wsgidav.error_printer import ErrorPrinter
from girder import logger
from girder import events
from girder.constants import ROOT_DIR
from girder.models.setting import Setting
from girder.utility import setting_utilities
from girder.constants import SettingDefault
from .constants import PluginSettings
from .lib.Authorizer import HomeAuthorizer, TaleAuthorizer
from .lib.DirectoryInitializer import HomeDirectoryInitializer, TaleDirectoryInitializer
from .lib.WTDomainController import WTDomainController
from .lib.WTFilesystemProvider import WTFilesystemProvider
from .lib.PathMapper import HomePathMapper, TalePathMapper
from .lib.WTAssetstoreTypes import WTAssetstoreTypes
from .lib.WTAssetstoreAdapter import WTHomeAssetstoreAdapter, WTTaleAssetstoreAdapter
from .lib.EventHandlers import *
from .resources.homedirpass import Homedirpass
from girder.utility.assetstore_utilities import *

HOME_DIRS_APPS = []


@setting_utilities.validator({
    PluginSettings.HOME_DIRS_ROOT,
})
def validateOtherSettings(event):
    pass

def pathRouter(h: EventHandler):
    def handler(event: Event):
        path = pathlib.Path(h.getPath(event))
        for (pathMapper, app) in HOME_DIRS_APPS:
            if pathMapper.girderPathMatches(path):
                provider = app.providerMap['/']['provider']
                logger.debug('Handling %s (%s) using %s' % (event, path, provider.rootFolderPath))
                try:
                    h.run(event, path, pathMapper, provider)
                except Exception as ex:
                    # hey, girder, when you have stuff like this that can be asynchroneous you
                    # need a mechanism to propagate errors so that the exception doesn't end up
                    # ignored in your event dispatch thread
                    raise
                return

    return handler

def startDAVServer(rootPath, directoryInitializer, authorizer, pathMapper, assetstoreType: int):
    if not os.path.exists(rootPath):
        os.makedirs(rootPath)

    provider = WTFilesystemProvider(rootPath, pathMapper, assetstoreType)
    realm = pathMapper.getRealm()
    config = DEFAULT_CONFIG.copy()
    # Accept basic authentication and assume access through HTTPS only. This (HTTPS when only
    # basic is accepted) is enforced by some clients.
    # The reason for not accepting digest authentication is that it would require storage of
    # unsalted password hashes on the server. Maybe that's OK, since one could store
    # HA1 (md5(username:realm:password)) as specified by the digest auth RFC, which would make
    # it harder to use pre-computed hashes. But for now, this seems simpler.
    config.update({
        'mount_path': '/' + realm,
        'wt_home_dirs_root': rootPath,
        'provider_mapping': {'/': provider},
        'user_mapping': {},
        'middleware_stack': [WsgiDavDirBrowser, directoryInitializer, authorizer,
                             HTTPAuthenticator, ErrorPrinter, WsgiDavDebugFilter],
        'acceptbasic': True,
        'acceptdigest': False,
        'defaultdigest': False,
        'domaincontroller': WTDomainController(realm),
        'server': 'cherrypy'
    })
    global HOME_DIRS_APPS
    app = WsgiDAVApp(config)
    HOME_DIRS_APPS.append((pathMapper, app))
    cherrypy.tree.graft(WsgiDAVApp(config), '/' + realm)

def setDefaults():
    if 'GIRDER_TEST_ASSETSTORE' in os.environ:
        assetstoreName = os.environ.get('GIRDER_TEST_ASSETSTORE', 'test')
        assetstorePath = os.path.join(
            ROOT_DIR, 'tests', 'assetstore', assetstoreName)
        SettingDefault.defaults[PluginSettings.HOME_DIRS_ROOT] = assetstorePath
    else:
        SettingDefault.defaults[PluginSettings.HOME_DIRS_ROOT] = '/tmp/wt-home-dirs'

    SettingDefault.defaults[PluginSettings.TALE_DIRS_ROOT] = '/tmp/wt-tale-dirs'

def addAssetstores():
    setAssetstoreAdapter(WTAssetstoreTypes.WT_HOME_ASSETSTORE, WTHomeAssetstoreAdapter)
    setAssetstoreAdapter(WTAssetstoreTypes.WT_TALE_ASSETSTORE, WTTaleAssetstoreAdapter)

def load(info):
    events.bind('model.folder.remove', 'wt_home_dir', pathRouter(FolderDeleteHandler()))
    events.bind('model.upload.assetstore', 'wt_home_dir', pathRouter(AssetstoreQueryHandler()))
    events.bind('model.folder.save', 'wt_home_dir', pathRouter(FolderSaveHandler()))
    events.bind('model.item.save', 'wt_home_dir', pathRouter(ItemSaveHandler()))

    setDefaults()
    addAssetstores()

    settings = Setting()

    homeDirsRoot = settings.get(PluginSettings.HOME_DIRS_ROOT)
    logger.info('WT Home Dirs root: %s' % homeDirsRoot)
    startDAVServer(homeDirsRoot, HomeDirectoryInitializer, HomeAuthorizer, HomePathMapper(),
                   WTAssetstoreTypes.WT_HOME_ASSETSTORE)

    taleDirsRoot = settings.get(PluginSettings.TALE_DIRS_ROOT)
    logger.info('WT Tale Dirs root: %s' % taleDirsRoot)
    startDAVServer(taleDirsRoot, TaleDirectoryInitializer, TaleAuthorizer, TalePathMapper(),
                   WTAssetstoreTypes.WT_TALE_ASSETSTORE)

    tree = cherrypy.tree
    print(tree)

    hdp = Homedirpass()
    info['apiRoot'].homedirpass = hdp
    info['apiRoot'].homedirpass.route('GET', ('generate',), hdp.generatePassword)
    info['apiRoot'].homedirpass.route('PUT', ('set',), hdp.setPassword)

