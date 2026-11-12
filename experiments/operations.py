"""API replica comparison and optional CPU autoscaling in the private Kind lab."""
import json
from runtime import LAB, capture, k, lab_connection, local, setup_lab, write_json
from workloads import registration_load


def hpa_object(name):
    if name not in ('waiting-room','allocation-worker'): raise ValueError('Unexpected HPA target')
    return dict(apiVersion='autoscaling/v2',kind='HorizontalPodAutoscaler',metadata=dict(name=name),
        spec=dict(scaleTargetRef=dict(apiVersion='apps/v1',kind='Deployment',name=name),
            minReplicas=1,maxReplicas=4,
            metrics=[dict(type='Resource',resource=dict(name='cpu',target=dict(type='Utilization',averageUtilization=60)))],
            behavior=dict(scaleUp=dict(stabilizationWindowSeconds=0,
                policies=[dict(type='Pods',value=1,periodSeconds=30)]),
                scaleDown=dict(stabilizationWindowSeconds=120,
                policies=[dict(type='Pods',value=1,periodSeconds=60)]))))


def autoscale(directory,install_metrics=False,disable=False):
    if disable:
        k('delete','hpa','waiting-room','allocation-worker','--ignore-not-found')
        result=dict(status='PASS',enabled=False)
    else:
        if install_metrics:
            # Fixed private Kind context; never reads or changes the user's current context.
            local.kubectl('apply','-f','https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.8.1/components.yaml',namespace=None)
            local.kubectl('patch','deployment','metrics-server','--type=json','-p',json.dumps([
                dict(op='add',path='/spec/template/spec/containers/0/args/-',value='--kubelet-insecure-tls')]),namespace='kube-system')
            local.kubectl('rollout','status','deployment/metrics-server','--timeout=180s',namespace='kube-system')
        local.kubectl('wait','--for=condition=Available','apiservice/v1beta1.metrics.k8s.io','--timeout=90s',namespace=None)
        for name in ('waiting-room','allocation-worker'):local.apply_object(hpa_object(name),LAB)
        result=dict(status='PASS',enabled=True,hpa=json.loads(k('get','hpa','-o','json',capture=True)),
            interpretation='Configured HPA, not proof of a scale-out. Record actual replicas, metrics and events under sustained load. '
            'The insecure kubelet TLS flag is restricted to this local Kind installation.')
    write_json(directory/'summary.json',result);return result


def scale_api(directory,rate=50,duration=30,repeats=3):
    if not 1<=repeats<=5:raise ValueError('Use 1-5 repeats')
    results=[]
    for repeat in range(repeats):
        for replicas in ([1,2,4] if repeat%2==0 else [4,2,1]):
            setup_lab(True,'demand-cycle',300,10)
            k('scale','deployment/waiting-room','--replicas='+str(replicas))
            k('rollout','status','deployment/waiting-room','--timeout=180s')
            child=directory/f'repeat-{repeat+1}-replicas-{replicas}';child.mkdir()
            with lab_connection() as base:
                write_json(child/'before.json',capture(base,'api-scale','before'))
                result=registration_load(base,child,rate,duration,'constant')
                write_json(child/'after.json',capture(base,'api-scale','after'))
            from collections import Counter
            rows=json.loads((child/'arrivals.json').read_text())
            result['served_by_instance']=dict(Counter(r['response'].get('instance') for r in rows if r.get('response',{}).get('instance')))
            result['replicas']=replicas;result['repeat']=repeat+1
            write_json(child/'summary.json',result);results.append(result)
    result=dict(status='PASS' if all(r['status']=='PASS' for r in results) else 'INCONCLUSIVE',results=results,
        interpretation='Identical offered rate/duration and seed; alternating replica order. '
        'A pass means workload completeness, not a throughput speedup. Port-forward and frontend can be bottlenecks.')
    write_json(directory/'summary.json',result);return result
