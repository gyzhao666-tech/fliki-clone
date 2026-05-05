"""auth · 权限服务（Track-24 RBAC v1）。

模块结构：

- ``rbac``：基于 ``team_members.role`` 的角色查询 + admin 判定（带邮箱白名单
  fallback 兜底，保留 demo@example.com 兼容）

未来扩展点（L-05 真做时）：
- ``permissions``：editor / viewer 的细粒度行为权限矩阵
- ``audit``：admin 行为审计 log
"""
from app.services.auth import rbac

__all__ = ["rbac"]
