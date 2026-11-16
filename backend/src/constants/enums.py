ROLES=('admin','analyst','viewer')
STATIONS=('北站','南站','东港')
RECEIPT_STATES=('delivered','reviewed')
TIMEZONE='Asia/Shanghai'
# 应到清单状态：待核对 → 可分发 / 有差异；换版或台账修订后旧核对失效。
MANIFEST_STATES=('pending','ready','blocked','superseded')
GATE_STATES=('ready','waiting','blocked','sent','paused')
RECONCILIATION_VERSION='manifest-reconcile-v1'
