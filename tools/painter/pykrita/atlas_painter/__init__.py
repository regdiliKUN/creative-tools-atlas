from krita import Krita
from .atlas_painter import AtlasPainterExtension

Krita.instance().addExtension(AtlasPainterExtension(Krita.instance()))

# 第十八轮：「Atlas 工坊」面板（设置 > 面板 > Atlas 工坊；工坊派活时会自动弹出）
try:
    from .atlas_studio import register as _register_studio
    _register_studio()
except Exception:
    import traceback
    traceback.print_exc()
