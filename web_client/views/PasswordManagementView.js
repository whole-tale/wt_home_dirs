import _ from 'underscore';

import View from 'girder/views/View';
import { wrap } from 'girder/utilities/PluginUtils';
import { apiRoot, restRequest } from 'girder/rest';
import events from 'girder/events';

import PasswordManagementViewTemplate from '../templates/passwordManagementView.pug';

var PasswordManagementView = View.extend({
    events: {
        'click #g-pm-generate': function (event) {
            this._generatePassword();
        },
        'click #g-pm-set': function (event) {
            this._setPassword($('#g-pm-password').val());
        },
    },
    initialize: function () {
        this.render();
    },
    render: function() {
        this.$el.html(PasswordManagementViewTemplate());
        return this;
    },
    _generatePassword: function() {
        this.$('#g-pm-password').val('');
        restRequest({
            type: 'GET',
            path: 'homedirpass/generate',
        }).done(_.bind(function (resp) {
            this.$('#g-pm-gpassword').val(resp['password']);
        }, this));
    },
    _setPassword: function(password) {
        this.$('#g-pm-gpassword').val('');
        restRequest({
            type: 'PUT',
            path: 'homedirpass/set',
            data: {
                password: JSON.stringify(password)
            }
        }).done(_.bind(function () {
            events.trigger('g:alert', {
                icon: 'ok',
                text: 'Password set.',
                type: 'success',
                timeout: 3000
            });
        }, this));
    }
});

export default PasswordManagementView;