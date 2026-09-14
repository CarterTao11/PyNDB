"""
数据库连接管理器
支持直连和SSH隧道模式
"""
import pymysql
import psycopg2
from psycopg2.extras import RealDictCursor
import pymysql.cursors
import paramiko
import socket
import threading
import io
import json
import os
import re
import time
import logging
from datetime import datetime as _dt, date as _date, time as _time, timedelta as _td
from decimal import Decimal
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from contextlib import contextmanager

logger = logging.getLogger(__name__)

from models.database import ConnectionModel


@dataclass
class DBConfig:
    """数据库配置"""
    db_type: str
    host: str
    port: int
    username: str
    password: str
    database_name: str
    charset: str = 'utf8mb4'
    mode: str = 'direct'  # 'direct' or 'ssh'
    
    # SSH配置
    ssh_host: str = ''
    ssh_port: int = 22
    ssh_username: str = ''
    ssh_auth_type: str = 'password'  # 'password' or 'key'
    ssh_password: str = ''
    ssh_private_key: str = ''
    ssh_key_passphrase: str = ''


class _SSHLocalForwarder:
    """基于 paramiko Transport 的本地端口转发器。

    替代已停止维护的 sshtunnel(其引用了 paramiko 5.x 中已删除的 DSSKey),
    并复用已建立认证的 SSH 连接, 不再重复登录。
    """

    def __init__(self, transport, remote_host, remote_port,
                 local_host='127.0.0.1', local_port=0):
        self._transport = transport
        self._remote = (remote_host, int(remote_port))
        self._local_host = local_host
        self._server = None
        self._running = False
        self.local_port = local_port
        if not local_port:
            self.local_port = self._find_free_port()

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]

    def start(self):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self._local_host, self.local_port))
        self._server.listen(100)
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while self._running:
            try:
                sock, _addr = self._server.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(sock,), daemon=True).start()

    def _handle(self, sock):
        chan = None
        try:
            chan = self._transport.open_channel(
                'direct-tcpip', self._remote, sock.getpeername(), timeout=10
            )
        except Exception as e:
            logger.warning("SSH隧道: 打开到 %s:%s 的转发通道被拒绝/失败: %s",
                           self._remote[0], self._remote[1], e)
        if chan is None:
            logger.warning("SSH隧道: 客户端连接 %s:%s 无法转发, 已关闭。常见原因: "
                           "SSH服务器禁用TCP转发(AllowTcpForwarding), 或SSH服务器无法访问目标地址",
                           self._remote[0], self._remote[1])
            try:
                sock.close()
            except Exception:
                pass
            return
        t1 = threading.Thread(target=self._pump, args=(sock, chan, 'sock->chan'), daemon=True)
        t2 = threading.Thread(target=self._pump, args=(chan, sock, 'chan->sock'), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        try:
            sock.close()
        except Exception:
            pass
        try:
            chan.close()
        except Exception:
            pass

    @staticmethod
    def _pump(src, dst, _direction):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        finally:
            try:
                if isinstance(dst, socket.socket):
                    dst.shutdown(socket.SHUT_WR)
                else:
                    dst.shutdown_write()
            except Exception:
                pass

    def stop(self):
        self._running = False
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, config: DBConfig):
        self.config = config
        self.ssh_tunnel = None
        self._ssh_client = None
        self.connection = None
        self.local_port = None
        
    def connect(self) -> Any:
        """建立数据库连接"""
        start_time = time.time()

        # 防御: 已有旧连接先整体关闭 (含SSH隧道), 避免占用双份服务端连接槽
        if self.connection is not None:
            self.close()

        # 如果是SSH模式，先建立隧道
        if self.config.mode == 'ssh':
            self._create_ssh_tunnel()
            db_host = '127.0.0.1'
            db_port = self.local_port
        else:
            db_host = self.config.host
            db_port = self.config.port
        
        if self.config.db_type == 'mysql':
            try:
                self.connection = pymysql.connect(
                    host=db_host,
                    port=db_port,
                    user=self.config.username,
                    password=self.config.password,
                    database=self.config.database_name,
                    cursorclass=pymysql.cursors.DictCursor,
                    charset=self.config.charset,
                    connect_timeout=10
                )
            except Exception as e:
                self._hint_ssh_target(e)
        elif self.config.db_type == 'postgresql':
            try:
                self.connection = psycopg2.connect(
                    host=db_host,
                    port=db_port,
                    user=self.config.username,
                    password=self.config.password,
                    database=self.config.database_name,
                    client_encoding=self.config.charset,
                    cursor_factory=RealDictCursor,
                    application_name='pyNDB',   # pg_stat_activity 中可识别
                    connect_timeout=10
                )
            except Exception as e:
                self._hint_ssh_target(e)

        latency_ms = int((time.time() - start_time) * 1000)
        return latency_ms

    def _hint_ssh_target(self, err: Exception):
        """SSH隧道模式下数据库连接失败时, 附加排查提示后重新抛出"""
        if self.config.mode != 'ssh':
            raise err
        logger.error("SSH隧道已建立, 但经它访问数据库 %s:%s 失败: %s",
                     self.config.host, self.config.port, err)
        raise RuntimeError(
            f"{err} | 提示: SSH登录({self.config.ssh_host})已成功, 但从该服务器访问 "
            f"数据库地址 {self.config.host}:{self.config.port} 失败。"
            f"请确认: 1) 数据库地址应填'从SSH服务器视角'可达的地址(数据库就在跳板机上才填127.0.0.1); "
            f"2) SSH服务器未禁用TCP转发(AllowTcpForwarding); "
            f"3) 可在SSH服务器上执行 nc -zv {self.config.host} {self.config.port} 验证连通性"
        ) from err
    
    def test_connection(self) -> Dict[str, Any]:
        """测试连接"""
        try:
            latency_ms = self.connect()
            version = self.get_version()
            self.close()
            return {
                'success': True,
                'serverVersion': version,
                'latencyMs': latency_ms,
                'message': '连接成功'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f'连接失败: {str(e)}'
            }
    
    def _load_ssh_pkey(self):
        """加载SSH私钥: 支持私钥文件路径, 也支持直接粘贴的私钥内容"""
        val = (self.config.ssh_private_key or '').strip()
        if not val:
            return None
        if not val.startswith('-----BEGIN'):
            # 私钥文件路径 → 读取内容
            with open(os.path.expanduser(val), 'r') as f:
                val = f.read().strip()
        password = self.config.ssh_key_passphrase or None
        # 依次尝试 RSA / Ed25519 / ECDSA
        last_err = None
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                return cls.from_private_key(io.StringIO(val), password=password)
            except paramiko.PasswordRequiredException:
                raise paramiko.PasswordRequiredException('私钥已加密, 请填写"私钥密码(passphrase)"')
            except Exception as e:
                last_err = e
        raise last_err if last_err else paramiko.SSHException('无法解析SSH私钥')

    def _create_ssh_tunnel(self):
        """创建SSH隧道"""
        self._close_ssh_tunnel()

        # 创建SSH客户端
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # 准备认证方式: 密钥(文件路径或粘贴内容) 或 密码
        pkey = self._load_ssh_pkey() if self.config.ssh_auth_type == 'key' else None

        connect_kwargs = dict(
            hostname=self.config.ssh_host,
            port=self.config.ssh_port,
            username=self.config.ssh_username,
        )
        if pkey is not None:
            connect_kwargs['pkey'] = pkey
        else:
            connect_kwargs['password'] = self.config.ssh_password

        # 先建立一次SSH连接 (复用它做端口转发, 不再重复登录)
        ssh.connect(**connect_kwargs)
        self._ssh_client = ssh

        # 在已认证的 SSH 连接上建立本地端口转发
        self.local_port = self._find_free_port()
        self.ssh_tunnel = _SSHLocalForwarder(
            ssh.get_transport(),
            self.config.host,
            self.config.port,
            '127.0.0.1',
            self.local_port
        )
        self.ssh_tunnel.start()
        logger.info("SSH隧道已建立: 127.0.0.1:%s -> %s:%s (经SSH服务器 %s)",
                    self.local_port, self.config.host, self.config.port, self.config.ssh_host)

    def _find_free_port(self) -> int:
        """查找可用端口"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]

    def _close_ssh_tunnel(self):
        """关闭SSH隧道"""
        if self.ssh_tunnel:
            try:
                self.ssh_tunnel.stop()
            except Exception:
                pass
            self.ssh_tunnel = None
        if self._ssh_client:
            try:
                self._ssh_client.close()
            except Exception:
                pass
            self._ssh_client = None
    
    def get_version(self) -> str:
        """获取数据库版本"""
        if self.config.db_type == 'mysql':
            sql = "SELECT VERSION() as version"
        else:
            sql = "SELECT version() as version"
        
        result = self.execute_sql(sql)
        if result['success'] and result['data']:
            row = result['data'][0]
            # 处理元组或字典格式
            if isinstance(row, dict):
                return row.get('version', '')
            elif isinstance(row, (list, tuple)):
                return str(row[0]) if row else ''
        return ''
    
    @staticmethod
    def _json_safe(v: Any) -> Any:
        """驱动返回对象 -> JSON友好值: datetime 统一为 yyyy-MM-dd HH:mm:ss 显示"""
        if isinstance(v, _dt):
            return v.strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(v, _date):
            return v.strftime('%Y-%m-%d')
        if isinstance(v, _time):
            return v.strftime('%H:%M:%S')
        if isinstance(v, _td):
            return str(v)
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, (dict, list)):
            # PG jsonb/json 由驱动解析为 dict/list, 统一转 JSON 字符串 (中文不转义)
            return json.dumps(v, ensure_ascii=False, default=str)
        if isinstance(v, (bytes, bytearray, memoryview)):
            b = bytes(v)
            try:
                return b.decode('utf-8')
            except UnicodeDecodeError:
                return b.hex()
        return v

    def execute_sql(self, sql: str) -> Dict[str, Any]:
        """执行SQL语句"""
        if not self.connection:
            self.connect()
        
        start_time = time.time()
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql)
                
                sql_upper = sql.strip().upper()
                is_select = sql_upper.startswith(('SELECT', 'SHOW', 'DESCRIBE', 'EXPLAIN', 'WITH'))
                
                if is_select:
                    results = cursor.fetchall()
                    execution_ms = int((time.time() - start_time) * 1000)
                    return {
                        'success': True,
                        'type': 'query',
                        'columns': [desc[0] for desc in cursor.description] if cursor.description else [],
                        'data': [
                            {k: self._json_safe(v) for k, v in row.items()} for row in results
                        ],
                        'rowCount': len(results),
                        'executionMs': execution_ms
                    }
                else:
                    self.connection.commit()
                    execution_ms = int((time.time() - start_time) * 1000)
                    return {
                        'success': True,
                        'type': 'modify',
                        'affectedRows': cursor.rowcount,
                        'executionMs': execution_ms,
                        'message': f'执行成功，影响 {cursor.rowcount} 行'
                    }
        except Exception as e:
            # 出错后回滚, 否则 psycopg2/pymysql 的事务会进入 aborted 状态,
            # 导致同一连接上的所有后续查询都失败
            try:
                self.connection.rollback()
            except Exception:
                pass
            return {
                'success': False,
                'error': str(e),
                'errorCode': getattr(e, 'errno', 0)
            }
    
    def get_databases(self) -> List[str]:
        """获取所有数据库"""
        if self.config.db_type == 'mysql':
            sql = "SHOW DATABASES"
        else:
            sql = "SELECT datname FROM pg_database WHERE datistemplate = false"
        
        result = self.execute_sql(sql)
        if result['success']:
            if self.config.db_type == 'mysql':
                return [row['Database'] for row in result['data'] 
                        if row['Database'] not in ('information_schema', 'mysql', 'performance_schema', 'sys')]
            else:
                return [row['datname'] for row in result['data']]
        return []
    
    def get_schemas(self) -> List[str]:
        """获取所有Schema (PostgreSQL)"""
        if self.config.db_type != 'postgresql':
            return []
        
        sql = "SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog', 'information_schema')"
        result = self.execute_sql(sql)
        if result['success']:
            return [row['schema_name'] for row in result['data']]
        return []
    
    def get_tables(self, database: str = None, schema: str = None) -> List[str]:
        """获取所有表"""
        if self.config.db_type == 'mysql':
            sql = "SHOW TABLES"
        else:
            schema = schema or 'public'
            sql = f"SELECT tablename FROM pg_tables WHERE schemaname = '{schema}'"
        
        result = self.execute_sql(sql)
        if result['success']:
            if self.config.db_type == 'mysql':
                return [list(row.values())[0] for row in result['data']]
            else:
                return [row['tablename'] for row in result['data']]
        return []
    
    def get_views(self, database: str = None, schema: str = None) -> List[str]:
        """获取所有视图"""
        if self.config.db_type == 'mysql':
            sql = "SELECT TABLE_NAME FROM information_schema.VIEWS WHERE TABLE_SCHEMA = DATABASE()"
        else:
            schema = schema or 'public'
            sql = f"SELECT viewname FROM pg_views WHERE schemaname = '{schema}'"
        
        result = self.execute_sql(sql)
        if result['success']:
            return [row['TABLE_NAME' if self.config.db_type == 'mysql' else 'viewname'] 
                    for row in result['data']]
        return []
    
    def get_table_info(self, table_name: str, schema: str = None) -> Dict[str, Any]:
        """获取表结构信息"""
        if self.config.db_type == 'mysql':
            # 表基本信息
            table_sql = f"""
                SELECT TABLE_NAME, TABLE_COMMENT, ENGINE, TABLE_COLLATION, CREATE_TIME
                FROM information_schema.TABLES 
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}'
            """
            table_result = self.execute_sql(table_sql)
            table_info = table_result['data'][0] if table_result['success'] and table_result['data'] else {}
            
            # 字段信息
            columns_sql = f"""
                SELECT 
                    COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
                    NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE,
                    COLUMN_DEFAULT, COLUMN_KEY, EXTRA, COLUMN_COMMENT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}'
                ORDER BY ORDINAL_POSITION
            """
            columns_result = self.execute_sql(columns_sql)
            columns = columns_result['data'] if columns_result['success'] else []
            
            # 索引信息
            index_sql = f"""
                SELECT INDEX_NAME, NON_UNIQUE, INDEX_TYPE, GROUP_CONCAT(COLUMN_NAME) as COLUMNS
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}'
                GROUP BY INDEX_NAME, NON_UNIQUE, INDEX_TYPE
            """
            index_result = self.execute_sql(index_sql)
            indexes = index_result['data'] if index_result['success'] else []
            
            # 外键信息
            fk_sql = f"""
                SELECT 
                    CONSTRAINT_NAME, COLUMN_NAME, 
                    REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME,
                    UPDATE_RULE, DELETE_RULE
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = '{table_name}'
                AND REFERENCED_TABLE_NAME IS NOT NULL
            """
            fk_result = self.execute_sql(fk_sql)
            foreign_keys = fk_result['data'] if fk_result['success'] else []
            
        else:
            # PostgreSQL
            schema = schema or 'public'
            
            # 表基本信息
            table_sql = f"""
                SELECT 
                    c.relname as table_name,
                    obj_description(c.oid, 'pg_class') as table_comment,
                    c.relkind
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = '{schema}' AND c.relname = '{table_name}'
            """
            table_result = self.execute_sql(table_sql)
            table_info = table_result['data'][0] if table_result['success'] and table_result['data'] else {}
            
            # 字段信息 (精确绑定到目标表: attrelid = 该表的 oid, 避免跨表同名列造成笛卡尔积)
            table_esc = table_name.replace("'", "''")
            schema_esc = (schema or 'public').replace("'", "''")
            columns_sql = f"""
                SELECT 
                    c.column_name, c.data_type, c.character_maximum_length,
                    c.numeric_precision, c.numeric_scale, c.is_nullable,
                    c.column_default,
                    col_description(a.attrelid, a.attnum) as column_comment,
                    (EXISTS (
                        SELECT 1 FROM pg_index i
                        WHERE i.indrelid = a.attrelid AND i.indisprimary
                          AND a.attnum = ANY(i.indkey)
                    )) as is_primary_key
                FROM information_schema.columns c
                JOIN pg_catalog.pg_class cls
                    ON cls.relname = c.table_name
                    AND cls.relnamespace = (SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = c.table_schema)
                JOIN pg_catalog.pg_attribute a
                    ON a.attrelid = cls.oid AND a.attname = c.column_name
                WHERE c.table_schema = '{schema_esc}' AND c.table_name = '{table_esc}'
                AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY c.ordinal_position
            """
            columns_result = self.execute_sql(columns_sql)
            columns = columns_result['data'] if columns_result['success'] else []
            
            # 索引信息
            index_sql = f"""
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = '{schema}' AND tablename = '{table_name}'
            """
            index_result = self.execute_sql(index_sql)
            indexes = index_result['data'] if index_result['success'] else []
            
            # 外键信息
            fk_sql = f"""
                SELECT
                    tc.constraint_name, kcu.column_name,
                    ccu.table_name AS referenced_table,
                    ccu.column_name AS referenced_column,
                    rc.update_rule, rc.delete_rule
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                JOIN information_schema.referential_constraints rc
                    ON tc.constraint_name = rc.constraint_name
                WHERE tc.table_schema = '{schema}' 
                    AND tc.table_name = '{table_name}'
                    AND tc.constraint_type = 'FOREIGN KEY'
            """
            fk_result = self.execute_sql(fk_sql)
            foreign_keys = fk_result['data'] if fk_result['success'] else []
        
        # 统一补充字段长度展示 (字符长度 / numeric 精度)
        for row in columns:
            row['length'] = self._fmt_column_length(row)

        return {
            'success': True,
            'table': table_info,
            'columns': columns,
            'indexes': indexes,
            'foreignKeys': foreign_keys
        }

    @staticmethod
    def _fmt_column_length(row: Dict[str, Any]) -> Any:
        """从 information_schema 行提取字段长度: 字符长度, 或 numeric(精度,小数位)"""
        for k_char, k_prec, k_scale in (
            ('CHARACTER_MAXIMUM_LENGTH', 'NUMERIC_PRECISION', 'NUMERIC_SCALE'),
            ('character_maximum_length', 'numeric_precision', 'numeric_scale'),
        ):
            if k_char in row and row[k_char] is not None:
                return row[k_char]
            if k_prec in row and row[k_prec] is not None:
                scale = row.get(k_scale)
                if scale not in (None, 0):  # 整型 scale=0 不展示无意义精度
                    return f"{row[k_prec]},{scale}"
        return None
    
    def get_table_data(self, table_name: str, limit: int = 100, offset: int = 0, 
                       order_by: str = None, order_dir: str = 'ASC') -> Dict[str, Any]:
        """获取表数据"""
        # MySQL 用反引号, PostgreSQL 用双引号
        if self.config.db_type == 'mysql':
            safe_table = f"`{table_name}`"
            quote = lambda name: f"`{name}`"
        else:
            safe_table = f'"{table_name}"'
            quote = lambda name: f'"{name}"'
        sql = f"SELECT * FROM {safe_table}"
        if order_by:
            sql += f" ORDER BY {quote(order_by)} {order_dir}"
        sql += f" LIMIT {limit} OFFSET {offset}"
        return self.execute_sql(sql)

    def update_cell(self, table_name: str, column: str, value: Any,
                    pk_values: Dict[str, Any]) -> Dict[str, Any]:
        """按主键更新单个字段 (参数化SQL, 值不拼入语句)"""
        if not pk_values:
            return {'success': False, 'error': '缺少主键条件, 无法定位记录'}

        if self.config.db_type == 'mysql':
            qi = lambda n: '`' + n.replace('`', '``') + '`'
        else:
            qi = lambda n: '"' + n.replace('"', '""') + '"'

        set_part = f"{qi(column)} = %s"
        where_parts = [f"{qi(k)} = %s" for k in pk_values]
        sql = f"UPDATE {qi(table_name)} SET {set_part} WHERE {' AND '.join(where_parts)}"
        params = [value] + list(pk_values.values())

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                affected = cursor.rowcount
            self.connection.commit()
            return {'success': True, 'affectedRows': affected, 'message': '更新成功'}
        except Exception as e:
            try:
                self.connection.rollback()
            except Exception:
                pass
            return {'success': False, 'error': str(e)}

    # ==================== 表结构修改 (DDL) ====================
    _IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

    def _qi(self, name: str) -> str:
        """标识符安全引用 (仅允许常规标识符, 杜绝注入)"""
        if not self._IDENT_RE.match(name or ''):
            raise ValueError(f'非法标识符: {name!r}')
        if self.config.db_type == 'mysql':
            return '`' + name + '`'
        return '"' + name + '"'

    @staticmethod
    def _validate_type(base_type: str, length=None) -> str:
        """类型白名单校验, 返回规范化类型串 (可带长度/精度, 如 VARCHAR(100) / NUMERIC(10,2))"""
        t = (base_type or '').strip().upper()
        if not re.match(r'^[A-Z][A-Z ]*$', t):
            raise ValueError(f'非法字段类型: {base_type!r}')
        if length is None or str(length).strip() == '':
            return t
        length = str(length).strip()
        if not re.match(r'^\d+(\s*,\s*\d+)?$', length):
            raise ValueError(f'非法长度/精度: {length!r} (示例: 100 或 10,2)')
        return f"{t}({length.replace(' ', '')})"

    @staticmethod
    def _default_sql(default) -> Optional[str]:
        """默认值转SQL: 关键字/数字原样, 其余按字符串字面量转义; 空 -> None"""
        if default is None or str(default).strip() == '':
            return None
        d = str(default).strip()
        kw = d.upper()
        if kw in ('CURRENT_TIMESTAMP', 'CURRENT_DATE', 'CURRENT_TIME', 'NULL', 'TRUE', 'FALSE'):
            return kw
        if re.match(r'^-?\d+(\.\d+)?$', d):
            return d
        return "'" + d.replace("'", "''") + "'"

    def _exec_ddl(self, statements: List[str], action: str) -> Dict[str, Any]:
        try:
            with self.connection.cursor() as cursor:
                for sql in statements:
                    logger.info('DDL(%s): %s', action, sql)
                    cursor.execute(sql)
            self.connection.commit()
            return {'success': True, 'message': f'{action}成功'}
        except Exception as e:
            try:
                self.connection.rollback()
            except Exception:
                pass
            logger.exception('DDL失败(%s)', action)
            return {'success': False, 'error': str(e)}

    def add_column(self, table_name: str, spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加字段: spec = {name, type, length, not_null, default, comment}"""
        try:
            col = self._qi(spec['name'])
            type_sql = self._validate_type(spec.get('type'), spec.get('length'))
            sql = f"ALTER TABLE {self._qi(table_name)} ADD COLUMN {col} {type_sql}"
            if spec.get('not_null'):
                sql += ' NOT NULL'
            dsql = self._default_sql(spec.get('default'))
            if dsql:
                sql += f' DEFAULT {dsql}'
            comment = (spec.get('comment') or '').strip()
            statements = [sql]
            if comment:
                if self.config.db_type == 'mysql':
                    statements[0] += " COMMENT '" + comment.replace("'", "''") + "'"
                else:
                    statements.append(
                        f"COMMENT ON COLUMN {self._qi(table_name)}.{col} IS '"
                        + comment.replace("'", "''") + "'"
                    )
            return self._exec_ddl(statements, f"添加字段 {spec['name']}")
        except (ValueError, KeyError) as e:
            return {'success': False, 'error': str(e)}

    def modify_column(self, table_name: str, old_name: str, spec: Dict[str, Any]) -> Dict[str, Any]:
        """修改字段: spec = {name(新名), type, length, not_null, default, comment,
        extra(原自增标记), default_same(默认值未改动), original_default}"""
        try:
            old = self._qi(old_name)
            new_name = (spec.get('name') or old_name).strip()
            type_sql = self._validate_type(spec.get('type'), spec.get('length'))
            not_null = bool(spec.get('not_null'))
            comment = (spec.get('comment') or '').strip()
            renamed = new_name != old_name

            if self.config.db_type == 'mysql':
                # MySQL MODIFY/CHANGE 重写整列定义, 未指定 DEFAULT 即清除默认值:
                # 默认值未改动时用原默认值, 避免误清; 自增标记原样保留
                default_same = bool(spec.get('default_same'))
                dsql = self._default_sql(spec.get('original_default')) if default_same \
                    else self._default_sql(spec.get('default'))
                if renamed:
                    sql = f"ALTER TABLE {self._qi(table_name)} CHANGE COLUMN {old} {self._qi(new_name)} {type_sql}"
                else:
                    sql = f"ALTER TABLE {self._qi(table_name)} MODIFY COLUMN {old} {type_sql}"
                if not_null:
                    sql += ' NOT NULL'
                if dsql:
                    sql += f' DEFAULT {dsql}'
                if 'auto_increment' in (spec.get('extra') or '').lower():
                    sql += ' AUTO_INCREMENT'
                if comment:
                    sql += " COMMENT '" + comment.replace("'", "''") + "'"
                statements = [sql]
            else:
                col = self._qi(new_name)
                statements = []
                if renamed:
                    statements.append(
                        f"ALTER TABLE {self._qi(table_name)} RENAME COLUMN {old} TO {col}"
                    )
                statements.append(
                    f"ALTER TABLE {self._qi(table_name)} ALTER COLUMN {col} TYPE {type_sql} "
                    f"USING {col}::{type_sql}"
                )
                statements.append(
                    f"ALTER TABLE {self._qi(table_name)} ALTER COLUMN {col} "
                    f"{'SET NOT NULL' if not_null else 'DROP NOT NULL'}"
                )
                if spec.get('default_same'):
                    pass  # 默认值未改动, 跳过 (保护 nextval 等序列默认)
                else:
                    dsql = self._default_sql(spec.get('default'))
                    statements.append(
                        f"ALTER TABLE {self._qi(table_name)} ALTER COLUMN {col} "
                        + (f'SET DEFAULT {dsql}' if dsql else 'DROP DEFAULT')
                    )
                if comment:
                    statements.append(
                        f"COMMENT ON COLUMN {self._qi(table_name)}.{col} IS '"
                        + comment.replace("'", "''") + "'"
                    )
            action = f"修改字段 {old_name}" + (f" -> {new_name}" if renamed else "")
            return self._exec_ddl(statements, action)
        except (ValueError, KeyError) as e:
            return {'success': False, 'error': str(e)}

    def drop_column(self, table_name: str, column: str) -> Dict[str, Any]:
        """删除字段"""
        try:
            sql = f"ALTER TABLE {self._qi(table_name)} DROP COLUMN {self._qi(column)}"
            return self._exec_ddl([sql], f"删除字段 {column}")
        except ValueError as e:
            return {'success': False, 'error': str(e)}

    # ==================== 索引管理 (DDL) ====================
    _INDEX_METHODS = {
        'mysql': {'BTREE', 'HASH', 'FULLTEXT'},
        'postgresql': {'btree', 'hash', 'gin', 'gist', 'brin'},
    }

    def create_index(self, table_name: str, spec: Dict[str, Any]) -> Dict[str, Any]:
        """新建索引: spec = {name?(空则自动生成), unique?, method?, columns: [{name, dir}]}"""
        try:
            cols = spec.get('columns') or []
            if not cols:
                return {'success': False, 'error': '请至少选择一个索引字段'}
            col_parts = []
            for c in cols:
                q = self._qi(c.get('name', ''))
                d = str(c.get('dir') or 'ASC').upper()
                if d not in ('ASC', 'DESC'):
                    raise ValueError(f'非法排序方向: {d!r}')
                col_parts.append(f'{q} {d}')

            unique = bool(spec.get('unique'))
            method = str(spec.get('method') or '').strip()
            name = (spec.get('name') or '').strip()
            if not name:
                stem = '_'.join(str(c.get('name', '')) for c in cols)
                name = f'idx_{table_name}_{stem}'
            if self.config.db_type != 'mysql' and len(name) > 63:
                name = name[:63]  # PG 标识符上限
            name_q = self._qi(name)

            if self.config.db_type == 'mysql':
                if method and method.upper() not in self._INDEX_METHODS['mysql']:
                    raise ValueError(f'非法索引方法: {method!r}')
                m = method.upper()
                prefix = 'UNIQUE ' if unique else ('FULLTEXT ' if m == 'FULLTEXT' else '')
                using = f' USING {m}' if m in ('BTREE', 'HASH') else ''
                sql = (f"CREATE {prefix}INDEX {name_q} ON {self._qi(table_name)}"
                       f"{using} ({', '.join(col_parts)})")
            else:
                if method and method.lower() not in self._INDEX_METHODS['postgresql']:
                    raise ValueError(f'非法索引方法: {method!r}')
                using = f' USING {method.lower()} ' if method else ' '
                sql = (f"CREATE {'UNIQUE ' if unique else ''}INDEX {name_q} "
                       f"ON {self._qi(table_name)}{using}({', '.join(col_parts)})")
            return self._exec_ddl([sql], f"新建索引 {name}")
        except ValueError as e:
            return {'success': False, 'error': str(e)}

    def drop_index(self, table_name: str, index_name: str, schema: str = None) -> Dict[str, Any]:
        """删除索引 (主键/约束自动创建的索引由数据库拒绝, 需通过约束删除)"""
        try:
            if self.config.db_type == 'mysql':
                sql = f"DROP INDEX {self._qi(index_name)} ON {self._qi(table_name)}"
            else:
                schema = schema or 'public'
                sql = f"DROP INDEX {self._qi(schema)}.{self._qi(index_name)}"
            return self._exec_ddl([sql], f"删除索引 {index_name}")
        except ValueError as e:
            return {'success': False, 'error': str(e)}
    
    def create_table(self, table_name: str, columns: List[Dict], 
                     comment: str = '', schema: str = None) -> Dict[str, Any]:
        """创建表"""
        if self.config.db_type == 'mysql':
            col_defs = []
            for col in columns:
                col_def = f"`{col['name']}` {col['type']}"
                if col.get('primary_key'):
                    col_def += " PRIMARY KEY"
                if col.get('auto_increment'):
                    col_def += " AUTO_INCREMENT"
                if not col.get('nullable', True):
                    col_def += " NOT NULL"
                if col.get('default') is not None:
                    col_def += f" DEFAULT {col['default']}"
                if col.get('comment'):
                    col_def += f" COMMENT '{col['comment']}'"
                col_defs.append(col_def)
            
            sql = f"CREATE TABLE `{table_name}` ({', '.join(col_defs)})"
            if comment:
                sql += f" COMMENT='{comment}'"
            sql += " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        else:
            schema = schema or 'public'
            col_defs = []
            for col in columns:
                col_def = f"{col['name']} {col['type']}"
                if col.get('primary_key'):
                    col_def += " PRIMARY KEY"
                if col.get('auto_increment'):
                    col_def += " GENERATED BY DEFAULT AS IDENTITY"
                if not col.get('nullable', True):
                    col_def += " NOT NULL"
                if col.get('default') is not None:
                    col_def += f" DEFAULT {col['default']}"
                col_defs.append(col_def)
            
            sql = f"CREATE TABLE {schema}.{table_name} ({', '.join(col_defs)})"
            if comment:
                sql += f"; COMMENT ON TABLE {schema}.{table_name} IS '{comment}'"
        
        return self.execute_sql(sql)
    
    def preview_ddl(self, table_name: str, columns: List[Dict], 
                    comment: str = '', schema: str = None) -> str:
        """生成DDL预览"""
        if self.config.db_type == 'mysql':
            lines = [f"CREATE TABLE `{table_name}` ("]
            for i, col in enumerate(columns):
                col_def = f"  `{col['name']}` {col['type']}"
                if col.get('primary_key'):
                    col_def += " PRIMARY KEY"
                if col.get('auto_increment'):
                    col_def += " AUTO_INCREMENT"
                if not col.get('nullable', True):
                    col_def += " NOT NULL"
                if col.get('default') is not None:
                    col_def += f" DEFAULT {col['default']}"
                if col.get('comment'):
                    col_def += f" COMMENT '{col['comment']}'"
                lines.append(col_def)
            lines.append(") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
            if comment:
                lines.append(f"COMMENT='{comment}'")
            return ",\n".join(lines[:-2]) + ",\n" + lines[-1] + ";"
        else:
            schema = schema or 'public'
            lines = [f'CREATE TABLE "{schema}"."{table_name}" (']
            for col in columns:
                col_def = f'  "{col["name"]}" {col["type"]}'
                if col.get('primary_key'):
                    col_def += " PRIMARY KEY"
                if not col.get('nullable', True):
                    col_def += " NOT NULL"
                if col.get('default') is not None:
                    col_def += f" DEFAULT {col['default']}"
                lines.append(col_def)
            lines.append(");")
            
            if comment:
                lines.append(f"COMMENT ON TABLE \"{schema}\".\"{table_name}\" IS '{comment}';")
            
            return ",\n".join(lines[:-1]) + ",\n" + lines[-1]
    
    def close(self):
        """关闭连接"""
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
        self._close_ssh_tunnel()


# 连接池管理
_active_connections = {}

def get_connection(conn_id: int) -> Optional[DatabaseManager]:
    """获取活动连接"""
    return _active_connections.get(conn_id)

def set_connection(conn_id: int, db: DatabaseManager):
    """设置活动连接"""
    _active_connections[conn_id] = db

def remove_connection(conn_id: int):
    """移除活动连接"""
    if conn_id in _active_connections:
        _active_connections[conn_id].close()
        del _active_connections[conn_id]
