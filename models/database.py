"""
数据模型 - 连接配置和查询历史
"""
import json
import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from utils.security import encrypt, decrypt
from utils.runtime import data_dir

DB_PATH = os.path.join(data_dir(), 'pyndb.db')

def get_db_path():
    """确保数据目录存在"""
    db_dir = os.path.dirname(DB_PATH)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
    return DB_PATH

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    
    # 连接配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS db_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            db_type TEXT NOT NULL,
            mode TEXT DEFAULT 'direct',
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            username TEXT NOT NULL,
            password_enc TEXT,
            database_name TEXT NOT NULL,
            charset TEXT DEFAULT 'utf8mb4',
            ssh_host TEXT,
            ssh_port INTEGER DEFAULT 22,
            ssh_username TEXT,
            ssh_auth_type TEXT DEFAULT 'password',
            ssh_password_enc TEXT,
            ssh_private_key_enc TEXT,
            ssh_key_passphrase_enc TEXT,
            remark TEXT,
            tags TEXT,
            group_name TEXT DEFAULT '默认',
            is_favorite INTEGER DEFAULT 0,
            is_enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_used_at TEXT
        )
    ''')
    
    # 查询历史表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS query_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connection_id INTEGER,
            connection_name TEXT,
            database_name TEXT,
            schema_name TEXT,
            sql_text TEXT NOT NULL,
            sql_type TEXT,
            success INTEGER DEFAULT 1,
            error_message TEXT,
            affected_rows INTEGER DEFAULT 0,
            execution_ms INTEGER DEFAULT 0,
            client_ip TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (connection_id) REFERENCES db_connections(id)
        )
    ''')
    
    # 审计日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            resource TEXT,
            detail TEXT,
            client_ip TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            connection_id INTEGER,
            connection_name TEXT,
            database_name TEXT,
            sql_text TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

class ConnectionModel:
    """连接配置模型"""
    
    @staticmethod
    def create(data: Dict[str, Any]) -> int:
        """创建连接"""
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO db_connections (
                name, db_type, mode, host, port, username, password_enc,
                database_name, charset, ssh_host, ssh_port, ssh_username,
                ssh_auth_type, ssh_password_enc, ssh_private_key_enc,
                ssh_key_passphrase_enc, remark, tags, group_name, is_favorite
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['name'], data['db_type'], data.get('mode', 'direct'),
            data['host'], data['port'], data['username'], encrypt(data.get('password', '')),
            data['database_name'], data.get('charset', 'utf8mb4'),
            data.get('ssh_host', ''), data.get('ssh_port', 22), data.get('ssh_username', ''),
            data.get('ssh_auth_type', 'password'), encrypt(data.get('ssh_password', '')),
            encrypt(data.get('ssh_private_key', '')), encrypt(data.get('ssh_key_passphrase', '')),
            data.get('remark', ''), json.dumps(data.get('tags', [])),
            data.get('group_name', '默认'), data.get('is_favorite', 0)
        ))
        
        conn.commit()
        last_id = cursor.lastrowid
        conn.close()
        return last_id
    
    @staticmethod
    def get_all() -> List[Dict]:
        """获取所有连接"""
        conn = sqlite3.connect(get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM db_connections ORDER BY updated_at DESC')
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            item = dict(row)
            # 解密敏感信息
            item['password'] = ''
            item['ssh_password'] = ''
            item['ssh_private_key'] = ''
            item['ssh_key_passphrase'] = ''
            if item.get('password_enc'):
                item['password'] = '******'
            if item.get('ssh_password_enc'):
                item['ssh_password'] = '******'
            results.append(item)
        
        return results
    
    @staticmethod
    def get_by_id(conn_id: int) -> Optional[Dict]:
        """获取单个连接"""
        conn = sqlite3.connect(get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM db_connections WHERE id = ?', (conn_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            item = dict(row)
            # 解密敏感信息
            item['password'] = decrypt(item.pop('password_enc', '') or '')
            item['ssh_password'] = decrypt(item.pop('ssh_password_enc', '') or '')
            item['ssh_private_key'] = decrypt(item.pop('ssh_private_key_enc', '') or '')
            item['ssh_key_passphrase'] = decrypt(item.pop('ssh_key_passphrase_enc', '') or '')
            return item
        return None
    
    @staticmethod
    def update(conn_id: int, data: Dict[str, Any]) -> bool:
        """更新连接"""
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        
        # 如果密码是 *****，不更新
        existing = ConnectionModel.get_by_id(conn_id)
        if existing:
            if data.get('password') == '******':
                data['password'] = existing.get('password', '')
            if data.get('ssh_password') == '******':
                data['ssh_password'] = existing.get('ssh_password', '')
            if data.get('ssh_private_key') == '******':
                data['ssh_private_key'] = existing.get('ssh_private_key', '')
        
        cursor.execute('''
            UPDATE db_connections SET
                name = ?, db_type = ?, mode = ?, host = ?, port = ?,
                username = ?, password_enc = ?, database_name = ?, charset = ?,
                ssh_host = ?, ssh_port = ?, ssh_username = ?, ssh_auth_type = ?,
                ssh_password_enc = ?, ssh_private_key_enc = ?, ssh_key_passphrase_enc = ?,
                remark = ?, tags = ?, group_name = ?, is_favorite = ?, is_enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (
            data['name'], data['db_type'], data.get('mode', 'direct'),
            data['host'], data['port'], data['username'], encrypt(data.get('password', '')),
            data['database_name'], data.get('charset', 'utf8mb4'),
            data.get('ssh_host', ''), data.get('ssh_port', 22), data.get('ssh_username', ''),
            data.get('ssh_auth_type', 'password'), encrypt(data.get('ssh_password', '')),
            encrypt(data.get('ssh_private_key', '')), encrypt(data.get('ssh_key_passphrase', '')),
            data.get('remark', ''), json.dumps(data.get('tags', [])),
            data.get('group_name', '默认'), data.get('is_favorite', 0),
            data.get('is_enabled', 1), conn_id
        ))
        
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0
    
    @staticmethod
    def delete(conn_id: int) -> bool:
        """删除连接"""
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        cursor.execute('DELETE FROM db_connections WHERE id = ?', (conn_id,))
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0
    
    @staticmethod
    def update_last_used(conn_id: int):
        """更新最后使用时间"""
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE db_connections SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?',
            (conn_id,)
        )
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_groups() -> List[str]:
        """获取所有分组"""
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT group_name FROM db_connections ORDER BY group_name')
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]


class QueryHistoryModel:
    """查询历史模型"""
    
    @staticmethod
    def add(data: Dict[str, Any]):
        """添加查询历史"""
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO query_history (
                connection_id, connection_name, database_name, schema_name,
                sql_text, sql_type, success, error_message, affected_rows,
                execution_ms, client_ip
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('connection_id'), data.get('connection_name'),
            data.get('database_name'), data.get('schema_name'),
            data['sql_text'], data.get('sql_type', 'SELECT'),
            1 if data.get('success', True) else 0,
            data.get('error_message', ''), data.get('affected_rows', 0),
            data.get('execution_ms', 0), data.get('client_ip', '')
        ))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_list(connection_id: int = None, limit: int = 100) -> List[Dict]:
        """获取查询历史"""
        conn = sqlite3.connect(get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if connection_id:
            cursor.execute(
                'SELECT * FROM query_history WHERE connection_id = ? ORDER BY created_at DESC LIMIT ?',
                (connection_id, limit)
            )
        else:
            cursor.execute(
                'SELECT * FROM query_history ORDER BY created_at DESC LIMIT ?',
                (limit,)
            )
        
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

class FavoriteModel:
    """收藏 SQL 模型"""
    
    @staticmethod
    def add(data: dict):
        conn = sqlite3.connect(get_db_path())
        conn.execute('''
            INSERT INTO favorites (name, connection_id, connection_name, database_name, sql_text)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            data['name'], data.get('connection_id'),
            data.get('connection_name', ''), data.get('database_name', ''),
            data['sql_text']
        ))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_list():
        conn = sqlite3.connect(get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM favorites ORDER BY created_at DESC')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    @staticmethod
    def delete(fav_id: int):
        conn = sqlite3.connect(get_db_path())
        conn.execute('DELETE FROM favorites WHERE id = ?', (fav_id,))
        conn.commit()
        conn.close()


# 初始化数据库
init_db()
