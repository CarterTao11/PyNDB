"""
pyNDB - 敏感信息加密工具
使用 Fernet (AES) 加密
"""
import logging
import os
from cryptography.fernet import Fernet
from typing import Optional

from utils.runtime import data_dir

logger = logging.getLogger(__name__)


def _key_file_path() -> str:
    """本地密钥文件路径: <可写根目录>/data/.fernet_key"""
    return os.path.join(data_dir(), '.fernet_key')


def _get_fernet_key() -> bytes:
    key = os.environ.get('FERNET_KEY', '')
    if key:
        return key.encode() if isinstance(key, str) else key

    # 环境变量未设置: 使用本地密钥文件保持密钥持久化(重启后已保存的密码仍可解密)
    key_file = _key_file_path()
    try:
        if os.path.exists(key_file):
            with open(key_file, 'r', encoding='utf-8') as f:
                stored = f.read().strip()
            if stored:
                return stored.encode()

        key = Fernet.generate_key().decode()
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        with open(key_file, 'w', encoding='utf-8') as f:
            f.write(key)
        logger.info("已生成本地密钥文件: %s (环境变量 FERNET_KEY 优先级更高)", key_file)
        return key.encode()
    except OSError:
        # 无法读写密钥文件时退回临时密钥(仅本次进程有效)
        logger.warning("无法读写密钥文件 %s, 使用临时密钥", key_file)
        return Fernet.generate_key()


# 全局密码实例
_cipher = None

def get_cipher() -> Fernet:
    global _cipher
    if _cipher is None:
        _cipher = Fernet(_get_fernet_key())
    return _cipher

def encrypt(plaintext: str) -> str:
    """加密字符串"""
    if not plaintext:
        return ''
    cipher = get_cipher()
    return cipher.encrypt(plaintext.encode()).decode()

def decrypt(ciphertext: str) -> str:
    """解密字符串"""
    if not ciphertext:
        return ''
    try:
        cipher = get_cipher()
        return cipher.decrypt(ciphertext.encode()).decode()
    except Exception:
        logger.warning("密码解密失败(密钥不匹配?), 返回空字符串, 请重新保存连接密码")
        return ''

def mask_password(password: str) -> str:
    """脱敏密码"""
    if not password:
        return ''
    if len(password) <= 4:
        return '****'
    return password[:2] + '****' + password[-2:]
