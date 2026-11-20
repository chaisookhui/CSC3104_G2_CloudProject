"""Public gateway security tests: prove that denied calls never reach services."""
import os
import unittest
from unittest.mock import Mock,patch
from frontend.server import create_app
from frontend.access import derived

TOKEN='test-private-payment-token-'+'x'*40

class GatewayAccessTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'PAYMENT_API_TOKEN':TOKEN,'FRONTEND_AUTH':'true'})
        self.env.start();self.addCleanup(self.env.stop)
        self.app=create_app();self.client=self.app.test_client()
        self.csrf=self.client.get('/api/session').get_json()['csrf']

    def post(self,path,body,client=None,csrf=None):
        return (client or self.client).post('/api/'+path,json=body,headers={'X-CSRF-Token':csrf or self.csrf})

    def test_unauthorized_admin_and_arbitrary_seat_mutations_never_forward(self):
        with patch('frontend.server.proxy_request') as upstream:
            for path in ('waiting-room/sale/start','seats/seats/confirm','allocation/batches','dispatcher/batches/next'):
                self.assertEqual(self.post(path,{}).status_code,403)
            upstream.assert_not_called()

    def test_forged_identity_and_cross_browser_booking_are_denied(self):
        user=self.post('session/identities',{'name':'Alice','key':'stable-identity-key'}).get_json()
        party={'user_id':user['user_id'],'request_id':'rid-123','allocation':{'hold_id':'hold-1'}}
        other=self.app.test_client();csrf=other.get('/api/session').get_json()['csrf']
        with patch('frontend.access.requests.get',return_value=Mock(status_code=200,json=lambda:party)),patch('frontend.server.proxy_request') as upstream:
            self.assertEqual(other.get('/api/waiting-room/requests/rid-123').status_code,403)
            self.assertEqual(self.post('waiting-room/submit',{'user_id':user['user_id']},other,csrf).status_code,403)
            self.assertEqual(self.post('payment/payments',{'request_id':'rid-123','hold_id':'different'}).status_code,403)
            upstream.assert_not_called()

    def test_owned_booking_and_idempotent_identity_survive_reload(self):
        body={'name':'Alice','key':'stable-identity-key'}
        user=self.post('session/identities',body).get_json()
        self.assertEqual(user,self.post('session/identities',body).get_json())
        self.assertIn(user,self.client.get('/api/session').get_json()['users'])
        party={'user_id':user['user_id'],'request_id':'rid-123'}
        response=Mock(status_code=200,content=b'{"request_id":"rid-123"}',headers={})
        with patch('frontend.access.requests.get',return_value=Mock(status_code=200,json=lambda:party)),patch('frontend.server.proxy_request',return_value=response):
            self.assertEqual(self.client.get('/api/waiting-room/requests/rid-123').status_code,200)

    def test_owned_hold_can_be_paid_or_cancelled(self):
        user=self.post('session/identities',{'name':'Alice','key':'stable-identity-key'}).get_json()
        party={'user_id':user['user_id'],'request_id':'rid-123','allocation':{'hold_id':'hold-1'}}
        response=Mock(status_code=200,content=b'{}',headers={})
        with patch('frontend.access.requests.get',return_value=Mock(status_code=200,json=lambda:party)),patch('frontend.server.proxy_request',return_value=response):
            for path in ('payment/payments','payment/checkouts/cancel'):
                with self.subTest(path=path):
                    self.assertEqual(self.post(path,{'request_id':'rid-123','hold_id':'hold-1'}).status_code,200)

    def test_csrf_and_invalid_admin_password_are_denied(self):
        self.assertEqual(self.client.post('/api/session/admin',json={'password':derived(TOKEN,'admin-password')}).status_code,403)
        self.assertEqual(self.post('session/admin',{'password':'wrong'}).status_code,403)
        self.assertEqual(self.post('session/admin',{'password':derived(TOKEN,'admin-password')}).status_code,200)
        self.assertTrue(self.client.get('/api/session').get_json()['admin'])
        self.post('session/logout',{})
        self.assertFalse(self.client.get('/api/session').get_json()['admin'])

    def test_queue_hides_other_browsers_and_token_never_reaches_browser(self):
        user=self.post('session/identities',{'name':'A','key':'stable-identity-key'}).get_json()
        response=Mock(status_code=200,json=lambda:dict(count=2,requests=[dict(user_id=user['user_id']),dict(user_id='other')]))
        with patch('frontend.server.proxy_request',return_value=response):
            data=self.client.get('/api/waiting-room/queue').get_json()
        self.assertEqual(data['requests'],[dict(user_id=user['user_id'])])
        self.assertNotIn(TOKEN,str(self.client.get('/api/session').get_json()))

    def test_operator_token_is_distinct_from_payment_token(self):
        response=Mock(status_code=200,content=b'{}',headers={})
        with patch('frontend.server.proxy_request',return_value=response) as upstream:
            self.assertEqual(self.client.post('/api/seats/seats/hold',json={},headers={'Authorization':'Bearer '+TOKEN}).status_code,403)
            upstream.assert_not_called()
            self.assertEqual(self.client.post('/api/seats/seats/hold',json={},headers={'Authorization':'Bearer '+derived(TOKEN,'operator')}).status_code,200)

    def test_secure_deployment_rejects_missing_or_weak_root_credential(self):
        for token in ('','short'):
            with patch.dict(os.environ,{'PAYMENT_API_TOKEN':token,'FRONTEND_AUTH':'true'}):
                with self.assertRaises(RuntimeError):create_app()

    def test_ownership_dependency_outage_is_retryable_and_never_forwards_mutation(self):
        import requests
        with patch('frontend.access.requests.get',side_effect=requests.Timeout()),patch('frontend.server.proxy_request') as upstream:
            self.assertEqual(self.client.get('/api/waiting-room/requests/rid-123').status_code,503)
            self.assertEqual(self.post('payment/payments',dict(request_id='rid-123',hold_id='h')).status_code,503)
            upstream.assert_not_called()

    def test_main_lab_and_compose_do_not_overwrite_each_others_browser_cookie(self):
        names=[]
        for namespace in ('csc3104','csc3104-lab','csc3104-compose'):
            with patch.dict(os.environ,{'EXPERIMENT_NAMESPACE':namespace}):
                app=create_app();names.append(app.config['SESSION_COOKIE_NAME'])
        self.assertEqual(len(set(names)),3)

if __name__=='__main__':unittest.main()
