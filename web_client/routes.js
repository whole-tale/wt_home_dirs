import router from 'girder/router';
import events from 'girder/events';
import { exposePluginConfig } from 'girder/utilities/PluginUtils';

exposePluginConfig('wt_sils', 'plugins/wt_home_dir/config');

import ConfigView from './views/ConfigView';
router.route('plugins/wt_home_dir/config', 'WTHomeDirConfig', function () {
    events.trigger('g:navigateTo', ConfigView);
});
