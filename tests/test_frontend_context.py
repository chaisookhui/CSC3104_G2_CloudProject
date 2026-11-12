"""The frontend identifies the actual target without exporting credentials."""
import os
import unittest
from unittest.mock import patch
from frontend.server import create_app


class FrontendContextTests(unittest.TestCase):
    def test_lab_context_is_explicit_and_contains_no_secret(self):
        with patch.dict(os.environ, {'EXPERIMENT_NAMESPACE':'csc3104-lab','PAYMENT_API_TOKEN':'private-token'}):
            context=create_app().test_client().get('/api/demo/context').get_json()
        self.assertTrue(context['is_lab'])
        self.assertEqual(context['namespace'],'csc3104-lab')
        self.assertEqual(set(context),{'namespace','is_lab','authentication'})
        self.assertNotIn('private-token',str(context))

    def test_main_or_unspecified_environment_never_claims_lab(self):
        for namespace in ('csc3104','local-or-compose',''):
            with patch.dict(os.environ, {'EXPERIMENT_NAMESPACE':namespace}):
                self.assertFalse(create_app().test_client().get('/api/demo/context').get_json()['is_lab'])


if __name__=='__main__': unittest.main()
