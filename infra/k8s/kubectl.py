"""Run the pinned kubectl against this checkout's cluster, without changing PATH.

Example: python infra/k8s/kubectl.py -n csc3104 get pods
"""
import sys

from local import CONTEXT, KUBECONFIG, kubectl_binary, run


def main():
    return run([kubectl_binary(), '--kubeconfig', KUBECONFIG, '--context', CONTEXT,
                *sys.argv[1:]], check=False)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
