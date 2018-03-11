#!/usr/bin/env python
# -*- coding: utf-8 -*-

from girder.api.rest import Resource
from girder.constants import AccessType
from girder.api import access
from girder.api.describe import Description, describeRoute


class Homedirpass(Resource):
    def initialize(self):
        self.name = 'homedirpass'
        self.exposeFields(level=AccessType.READ, fields={})

    def validate(self, password):
        return password

    @access.user
    @describeRoute(
        Description('Sets the Home Dir password for a user.')
        .param('password', 'The password to set.', paramType='formData', required=True)
    )
    def setPassword(self, params):
        user = self.getCurrentUser()
        self.model('password', 'wt_home_dir').setPassword(user, params['password'])

    @access.user
    @describeRoute(
        Description('Generate, set, and return a Home Dir password for a user.')
    )
    def generatePassword(self, params):
        user = self.getCurrentUser()
        return self.model('password', 'wt_home_dir').generateAndSetPassword(user)
