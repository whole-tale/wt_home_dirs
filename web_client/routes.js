import router from 'girder/router';
import events from 'girder/events';
import exposePluginConfig from 'girder/utilities/PluginUtils';

import ConfigView from './views/ConfigView';
import PasswordManagementView from './views/PasswordManagementView';

exposePluginConfig('wt_home_dir', 'plugins/wt_home_dir/config');

router.route('plugins/wt_home_dir/config', 'WTHomeDirConfig', function () {
    events.trigger('g:navigateTo', ConfigView);
});

router.route('homedir/password', 'WTHomeDirPassword', function () {
    events.trigger('g:navigateTo', PasswordManagementView);
});
