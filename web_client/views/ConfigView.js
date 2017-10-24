import _ from 'underscore';

import PluginConfigBreadcrumbWidget from 'girder/views/widgets/PluginConfigBreadcrumbWidget';
import View from 'girder/views/View';
import { apiRoot, restRequest } from 'girder/rest';
import events from 'girder/events';

import ConfigViewTemplate from '../templates/configView.pug';
import '../stylesheets/configView.styl';

// should probably have an abstract version of this file

var ConfigView = View.extend({
    SETTING_KEYS: [
        'wt.homedir.root'
    ],

    settingControlId: function (key) {
        return '#g-wt-homedir-' + key.substring(5).replace(/_/g, '-');
    },

    events: {
        'submit .g-wt-homedir-config-form': function (event) {
            event.preventDefault();

            var slist = this.SETTING_KEYS.map(function (key) {
                return {
                    key: key,
                    value: this.$(this.settingControlId(key)).val().trim()
                };
            }, this);

            this._saveSettings(slist);
        }
    },

    initialize: function () {
        restRequest({
            type: 'GET',
            path: 'system/setting',
            data: {
                list: JSON.stringify(this.SETTING_KEYS)
            }
        }).done(_.bind(function (resp) {
            console.log('Settings: ', resp);
            this.settingVals = resp;
            this.render();
        }, this));
    },

    render: function () {
        var origin = window.location.protocol + '//' + window.location.host;
        var _apiRoot = apiRoot;

        if (apiRoot.substring(0, 1) !== '/') {
            _apiRoot = '/' + apiRoot;
        }

        this.$el.html(ConfigViewTemplate({
            origin: origin,
            apiRoot: _apiRoot
        }));

        if (!this.breadcrumb) {
            this.breadcrumb = new PluginConfigBreadcrumbWidget({
                pluginName: 'WholeTale Home Directory',
                el: this.$('.g-config-breadcrumb-container'),
                parentView: this
            }).render();
        }

        if (this.settingVals) {
            for (var i in this.SETTING_KEYS) {
                var key = this.SETTING_KEYS[i];
                this.$(this.settingControlId(key)).val(this.settingVals[key]);
            }
        }

        return this;
    },

    _saveSettings: function (providerId, settings) {
        restRequest({
            type: 'PUT',
            path: 'system/setting',
            data: {
                list: JSON.stringify(settings)
            },
            error: null
        }).done(_.bind(function () {
            events.trigger('g:alert', {
                icon: 'ok',
                text: 'Settings saved.',
                type: 'success',
                timeout: 3000
            });
        }, this)).error(_.bind(function (resp) {
            this.$('#g-wt-homedir-config-error-message').text(resp.responseJSON.message);
        }, this));
    }
});

export default ConfigView;

