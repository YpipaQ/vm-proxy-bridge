"""proxy-bridge v2 包。

模块边界（唯一事实来源 = MODULES.md，勿在别处重复描述）：
    paths      路径解析（XDG）          零副作用，只算路径
    config     配置读取与合并           只读 TOML + config.d/*.json 覆盖
    state      状态机 / flock / tx      唯一允许"写变更"的入口
    logs       结构化日志 + 内部轮转     只追加，永不抛
    backup     备份 / 还原 / 保留策略
    probe      上游 / 端口 / 出口 IP
    tunnel     TCP 转发器（长驻）
    entry      ~/.local/bin/proxy 稳定入口
    sysproxy   系统代理（GNOME gsettings，可逆）
    ui         Tk 界面（只发命令）
    cli        参数解析与输出，不做副作用
"""

__version__ = "0.1.0"
