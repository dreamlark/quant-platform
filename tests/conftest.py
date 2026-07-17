"""pytest 配置：统一把仓库根注入 sys.path。

修复 §五.14：部分测试文件未注入 ROOT，裸 ``pytest`` 直跑会因采集失败而漏跑；
此 conftest 在采集前注入，保证 ``pytest`` 与 ``python -m pytest`` 行为一致。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
