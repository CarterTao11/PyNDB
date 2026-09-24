"""
API 路由
"""
import time
from flask import Blueprint, request, jsonify, session
from models.database import ConnectionModel, QueryHistoryModel, FavoriteModel
from utils.db_manager import DatabaseManager, DBConfig, get_connection as get_active_connection, set_connection, remove_connection
from utils.log_config import setup_logging

# logging.basicConfig(stream=True)
logger = setup_logging()

api = Blueprint('api', __name__, url_prefix='/api/v1')

# 危险SQL关键词
DANGEROUS_SQL_PATTERNS = [
    (r'^\s*DELETE\s+FROM\s+\w+\s*$', 'DELETE 无 WHERE 条件'),
    (r'^\s*UPDATE\s+\w+\s+SET\s+\w+\s*=\s*\w+\s*$', 'UPDATE 无 WHERE 条件'),
    (r'^\s*DROP\s+TABLE', 'DROP TABLE'),
    (r'^\s*DROP\s+DATABASE', 'DROP DATABASE'),
    (r'^\s*TRUNCATE\s+', 'TRUNCATE'),
    (r'^\s*ALTER\s+TABLE\s+\w+\s+DROP', 'ALTER 删除字段'),
]

def check_dangerous_sql(sql: str) -> tuple:
    """检查危险SQL"""
    import re
    for pattern, message in DANGEROUS_SQL_PATTERNS:
        if re.match(pattern, sql, re.IGNORECASE):
            return True, message
    return False, ''


# ==================== 连接管理 ====================

@api.route('/connections', methods=['GET'])
def get_connections():
    """获取所有连接"""
    connections = ConnectionModel.get_all()
    return jsonify({'success': True, 'connections': connections})


@api.route('/connections/<int:conn_id>', methods=['GET'])
def get_connection_detail(conn_id):
    """获取单个连接"""
    conn = ConnectionModel.get_by_id(conn_id)
    if conn:
        return jsonify({'success': True, 'connection': conn})
    return jsonify({'success': False, 'error': '连接不存在'}), 404


@api.route('/connections', methods=['POST'])
def create_connection():
    """创建连接"""
    data = request.json
    
    is_redis = data.get('db_type') == 'redis'
    is_mongo = data.get('db_type') == 'mongodb'
    required = ['name', 'db_type', 'host', 'port']
    # Redis/MongoDB 不需要数据库名, SQL数据库需要
    if not is_redis and not is_mongo:
        required += ['username', 'database_name']
    for field in required:
        if not data.get(field):
            return jsonify({'success': False, 'error': f'缺少必填字段: {field}'}), 400
    
    conn_id = ConnectionModel.create(data)
    return jsonify({'success': True, 'id': conn_id, 'message': '创建成功'})


@api.route('/connections/<int:conn_id>', methods=['PUT'])
def update_connection(conn_id):
    """更新连接"""
    data = request.json
    if ConnectionModel.update(conn_id, data):
        return jsonify({'success': True, 'message': '更新成功'})
    return jsonify({'success': False, 'error': '更新失败'}), 400


@api.route('/connections/<int:conn_id>', methods=['DELETE'])
def delete_connection(conn_id):
    """删除连接"""
    # 关闭活动连接
    remove_connection(conn_id)
    
    if ConnectionModel.delete(conn_id):
        return jsonify({'success': True, 'message': '删除成功'})
    return jsonify({'success': False, 'error': '删除失败'}), 400


@api.route('/connections/<int:conn_id>/test', methods=['POST'])
def test_connection(conn_id):
    """测试连接"""
    conn = ConnectionModel.get_by_id(conn_id)
    if not conn:
        return jsonify({'success': False, 'error': '连接不存在'}), 404
    
    config = DBConfig(
        db_type=conn['db_type'],
        host=conn['host'],
        port=conn['port'],
        username=conn['username'],
        password=conn['password'],
        database_name=conn['database_name'],
        charset=conn.get('charset', 'utf8mb4'),
        mode=conn.get('mode', 'direct'),
        ssh_host=conn.get('ssh_host', ''),
        ssh_port=conn.get('ssh_port', 22),
        ssh_username=conn.get('ssh_username', ''),
        ssh_auth_type=conn.get('ssh_auth_type', 'password'),
        ssh_password=conn.get('ssh_password', ''),
        ssh_private_key=conn.get('ssh_private_key', ''),
        ssh_key_passphrase=conn.get('ssh_key_passphrase', '')
    )
    
    db = DatabaseManager(config)
    result = db.test_connection()
    db.close()
    
    return jsonify(result)


@api.route('/connections/test', methods=['POST'])
def test_new_connection():
    """测试新连接"""
    data = request.json
    logger.info(f"测试连接: {data.get('db_type')} {data.get('host')}:{data.get('port')}")
    
    config = DBConfig(
        db_type=data.get('db_type', 'mysql'),
        host=data.get('host', 'localhost'),
        port=int(data.get('port', 3306)),
        username=data.get('username', ''),
        password=data.get('password', ''),
        database_name=data.get('database_name', ''),
        charset=data.get('charset', 'utf8mb4'),
        mode=data.get('mode', 'direct'),
        ssh_host=data.get('ssh_host', ''),
        ssh_port=int(data.get('ssh_port', 22)),
        ssh_username=data.get('ssh_username', ''),
        ssh_auth_type=data.get('ssh_auth_type', 'password'),
        ssh_password=data.get('ssh_password', ''),
        ssh_private_key=data.get('ssh_private_key', ''),
        ssh_key_passphrase=data.get('ssh_key_passphrase', '')
    )
    
    db = DatabaseManager(config)
    result = db.test_connection()
    
    logger.info(f"测试结果: {result}")
    db.close()
    
    return jsonify(result)


@api.route('/connections/<int:conn_id>/connect', methods=['POST'])
def connect_to_database(conn_id):
    """连接到数据库"""
    conn = ConnectionModel.get_by_id(conn_id)
    if not conn:
        return jsonify({'success': False, 'error': '连接不存在'}), 404
    
    logger.info("连接数据库: conn_id=%s, db_type=%s, host=%s:%s",
                conn_id, conn.get('db_type'), conn.get('host'), conn.get('port'))
    
    # 如果已有活动连接，先关闭
    remove_connection(conn_id)
    
    config = DBConfig(
        db_type=conn['db_type'],
        host=conn['host'],
        port=conn['port'],
        username=conn['username'],
        password=conn['password'],
        database_name=conn['database_name'],
        charset=conn.get('charset', 'utf8mb4'),
        mode=conn.get('mode', 'direct'),
        ssh_host=conn.get('ssh_host', ''),
        ssh_port=conn.get('ssh_port', 22),
        ssh_username=conn.get('ssh_username', ''),
        ssh_auth_type=conn.get('ssh_auth_type', 'password'),
        ssh_password=conn.get('ssh_password', ''),
        ssh_private_key=conn.get('ssh_private_key', ''),
        ssh_key_passphrase=conn.get('ssh_key_passphrase', '')
    )
    
    try:
        db = DatabaseManager(config)
        latency_ms = db.connect()

        # 获取数据库信息
        version = db.get_version()
        tables = db.get_tables()

        logger.info(f"连接成功: {version}, {len(tables)} tables")

        # 保存连接
        set_connection(conn_id, db)

        # 更新最后使用时间
        ConnectionModel.update_last_used(conn_id)

        return jsonify({
            'success': True,
            'conn_id': conn_id,
            'version': version,
            'tables': tables,
            'latencyMs': latency_ms,
            'message': '连接成功'
        })
    except Exception as e:
        # 连接半途失败 (如已连上但取版本/表清单出错): 显式释放, 不留孤儿连接
        try:
            if db is not None:
                db.close()
        except Exception:
            pass
        logger.exception("连接失败: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@api.route('/connections/<int:conn_id>/disconnect', methods=['POST'])
def disconnect_from_database(conn_id):
    """断开连接"""
    remove_connection(conn_id)
    return jsonify({'success': True, 'message': '已断开连接'})


@api.route('/connections/groups', methods=['GET'])
def get_connection_groups():
    """获取连接分组"""
    groups = ConnectionModel.get_groups()
    return jsonify({'success': True, 'groups': groups})


# ==================== SQL执行 ====================

@api.route('/query/execute', methods=['POST'])
def execute_query():
    """执行SQL"""
    data = request.json
    conn_id = data.get('connectionId')
    sql = data.get('sql', '').strip()
    
    if not conn_id or not sql:
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    
    # 获取连接
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    # 检查危险SQL
    is_dangerous, danger_msg = check_dangerous_sql(sql)
    if is_dangerous:
        return jsonify({
            'success': False, 
            'error': f'危险操作: {danger_msg}',
            'dangerous': True,
            'dangerMessage': danger_msg
        }), 400
    
    # 执行SQL
    result = db.execute_sql(sql)
    
    # 记录查询历史
    conn = ConnectionModel.get_by_id(conn_id)
    QueryHistoryModel.add({
        'connection_id': conn_id,
        'connection_name': conn['name'] if conn else '',
        'database_name': conn['database_name'] if conn else '',
        'sql_text': sql,
        'sql_type': result.get('type', 'UNKNOWN'),
        'success': result['success'],
        'error_message': result.get('error', ''),
        'affected_rows': result.get('affectedRows', 0) or result.get('rowCount', 0),
        'execution_ms': result.get('executionMs', 0),
        'client_ip': request.remote_addr
    })
    
    return jsonify(result)


@api.route('/query/force-execute', methods=['POST'])
def force_execute_query():
    """强制执行危险SQL（二次确认后）"""
    data = request.json
    conn_id = data.get('connectionId')
    sql = data.get('sql', '').strip()
    
    if not conn_id or not sql:
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    result = db.execute_sql(sql)
    
    # 记录
    conn = ConnectionModel.get_by_id(conn_id)
    QueryHistoryModel.add({
        'connection_id': conn_id,
        'connection_name': conn['name'] if conn else '',
        'database_name': conn['database_name'] if conn else '',
        'sql_text': sql,
        'sql_type': result.get('type', 'UNKNOWN'),
        'success': result['success'],
        'error_message': result.get('error', ''),
        'affected_rows': result.get('affectedRows', 0) or result.get('rowCount', 0),
        'execution_ms': result.get('executionMs', 0),
        'client_ip': request.remote_addr
    })
    
    return jsonify(result)


@api.route('/query/history', methods=['GET'])
def get_query_history():
    """获取查询历史"""
    conn_id = request.args.get('connection_id', type=int)
    limit = request.args.get('limit', 100, type=int)
    
    history = QueryHistoryModel.get_list(conn_id, limit)
    return jsonify({'success': True, 'history': history})


@api.route('/favorites', methods=['GET'])
def get_favorites():
    """获取收藏列表"""
    favorites = FavoriteModel.get_list()
    return jsonify({'success': True, 'favorites': favorites})


@api.route('/favorites', methods=['POST'])
def add_favorite():
    """添加收藏"""
    data = request.json
    if not data or not data.get('name') or not data.get('sql_text'):
        return jsonify({'success': False, 'error': '缺少名称或SQL'}), 400
    FavoriteModel.add(data)
    return jsonify({'success': True, 'message': '收藏成功'})


@api.route('/favorites/<int:fav_id>', methods=['DELETE'])
def delete_favorite(fav_id):
    """删除收藏"""
    FavoriteModel.delete(fav_id)
    return jsonify({'success': True, 'message': '已删除'})


# ==================== 元数据 ====================

@api.route('/metadata/databases', methods=['GET'])
def get_databases():
    """获取数据库列表"""
    conn_id = request.args.get('connectionId', type=int)
    if not conn_id:
        return jsonify({'success': False, 'error': '缺少connectionId'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    databases = db.get_databases()
    return jsonify({'success': True, 'databases': databases})


@api.route('/metadata/schemas', methods=['GET'])
def get_schemas():
    """获取Schema列表"""
    conn_id = request.args.get('connectionId', type=int)
    if not conn_id:
        return jsonify({'success': False, 'error': '缺少connectionId'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    schemas = db.get_schemas()
    return jsonify({'success': True, 'schemas': schemas})


@api.route('/metadata/tables', methods=['GET'])
def get_tables():
    """获取表列表"""
    conn_id = request.args.get('connectionId', type=int)
    database = request.args.get('database')
    schema = request.args.get('schema')
    
    if not conn_id:
        return jsonify({'success': False, 'error': '缺少connectionId'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    tables = db.get_tables(database, schema)
    return jsonify({'success': True, 'tables': tables})


@api.route('/metadata/views', methods=['GET'])
def get_views():
    """获取视图列表"""
    conn_id = request.args.get('connectionId', type=int)
    database = request.args.get('database')
    schema = request.args.get('schema')
    
    if not conn_id:
        return jsonify({'success': False, 'error': '缺少connectionId'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    views = db.get_views(database, schema)
    return jsonify({'success': True, 'views': views})


@api.route('/metadata/table/describe', methods=['GET'])
def describe_table():
    """获取表描述"""
    conn_id = request.args.get('connectionId', type=int)
    table_name = request.args.get('table')
    schema = request.args.get('schema')
    
    if not conn_id or not table_name:
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    result = db.get_table_info(table_name, schema)
    return jsonify(result)


# ==================== 表操作 ====================

@api.route('/table/preview-ddl', methods=['POST'])
def preview_ddl():
    """预览DDL"""
    data = request.json
    conn_id = data.get('connectionId')
    table_name = data.get('tableName')
    columns = data.get('columns', [])
    comment = data.get('comment', '')
    schema = data.get('schema')
    
    if not conn_id or not table_name or not columns:
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    ddl = db.preview_ddl(table_name, columns, comment, schema)
    return jsonify({'success': True, 'ddl': ddl})


@api.route('/table/create', methods=['POST'])
def create_table():
    """创建表"""
    data = request.json
    conn_id = data.get('connectionId')
    table_name = data.get('tableName')
    columns = data.get('columns', [])
    comment = data.get('comment', '')
    schema = data.get('schema')
    
    if not conn_id or not table_name or not columns:
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    result = db.create_table(table_name, columns, comment, schema)
    return jsonify(result)


@api.route('/table/data', methods=['GET'])
def get_table_data():
    """获取表数据"""
    conn_id = request.args.get('connectionId', type=int)
    table_name = request.args.get('table')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    order_by = request.args.get('orderBy')
    order_dir = request.args.get('orderDir', 'ASC')
    
    if not conn_id or not table_name:
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    result = db.get_table_data(table_name, limit, offset, order_by, order_dir)
    return jsonify(result)


@api.route('/table/update-cell', methods=['POST'])
def update_table_cell():
    """编辑保存单元格 (按主键更新)"""
    data = request.json
    conn_id = data.get('connectionId')
    table = data.get('table')
    column = data.get('column')
    value = data.get('value')
    pk = data.get('pk') or {}

    if not conn_id or not table or not column or not pk:
        return jsonify({'success': False, 'error': '缺少参数'}), 400

    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400

    logger.info("编辑保存: table=%s, column=%s, pk=%s", table, column, pk)
    result = db.update_cell(table, column, value, pk)
    return jsonify(result)


@api.route('/table/add-column', methods=['POST'])
def add_table_column():
    """添加字段"""
    data = request.json
    conn_id = data.get('connectionId')
    table = data.get('table')
    spec = data.get('column') or {}
    if not conn_id or not table or not spec.get('name'):
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    return jsonify(db.add_column(table, spec))


@api.route('/table/modify-column', methods=['POST'])
def modify_table_column():
    """修改字段 (类型/长度/可空/默认值/注释/改名)"""
    data = request.json
    conn_id = data.get('connectionId')
    table = data.get('table')
    old_name = data.get('oldName')
    spec = data.get('column') or {}
    if not conn_id or not table or not old_name or not spec.get('name'):
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    return jsonify(db.modify_column(table, old_name, spec))


@api.route('/table/drop-column', methods=['POST'])
def drop_table_column():
    """删除字段"""
    data = request.json
    conn_id = data.get('connectionId')
    table = data.get('table')
    column = data.get('column')
    if not conn_id or not table or not column:
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    return jsonify(db.drop_column(table, column))


@api.route('/table/create-index', methods=['POST'])
def create_table_index():
    """新建索引"""
    data = request.json
    conn_id = data.get('connectionId')
    table = data.get('table')
    spec = data.get('index') or {}
    if not conn_id or not table:
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    return jsonify(db.create_index(table, spec))


@api.route('/table/drop-index', methods=['POST'])
def drop_table_index():
    """删除索引"""
    data = request.json
    conn_id = data.get('connectionId')
    table = data.get('table')
    name = data.get('name')
    schema = data.get('schema')
    if not conn_id or not table or not name:
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    return jsonify(db.drop_index(table, name, schema))


# ==================== 导出 ====================

@api.route('/export/csv', methods=['POST'])
def export_csv():
    """导出CSV"""
    data = request.json
    conn_id = data.get('connectionId')
    sql = data.get('sql')
    
    if not conn_id or not sql:
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    result = db.execute_sql(sql)
    if not result['success']:
        return jsonify(result)
    
    # 生成CSV
    import csv
    import io
    
    output = io.StringIO()
    if result['columns']:
        output.write(','.join(result['columns']) + '\n')
        for row in result['data']:
            values = [str(row.get(col, '')) for col in result['columns']]
            output.write(','.join(values) + '\n')
    
    csv_content = output.getvalue()
    
    return jsonify({
        'success': True,
        'type': 'csv',
        'content': csv_content,
        'rowCount': result['rowCount']
    })


# ==================== Redis 操作 ====================


@api.route('/redis/keys', methods=['GET'])
def redis_keys():
    """获取 Redis 键列表"""
    conn_id = request.args.get('connectionId', type=int)
    pattern = request.args.get('pattern', '*')
    db = get_active_connection(conn_id)
    if not db or db.config.db_type != 'redis':
        return jsonify({'success': False, 'error': '未连接Redis'}), 400
    try:
        keys = db.connection.keys(pattern)
        # 获取每个key的类型和长度
        result = []
        for key in keys:
            key_type = db.connection.type(key)
            ttl = db.connection.ttl(key)
            if key_type == 'string':
                try:
                    val = db.connection.get(key)
                    length = len(val or '')
                except Exception:
                    length = 0
            elif key_type == 'list':
                length = db.connection.llen(key)
            elif key_type == 'set':
                length = db.connection.scard(key)
            elif key_type == 'zset':
                length = db.connection.zcard(key)
            elif key_type == 'hash':
                length = db.connection.hlen(key)
            else:
                length = 0
            result.append({'key': key, 'type': key_type, 'length': length, 'ttl': ttl})
        return jsonify({'success': True, 'keys': result, 'total': len(result)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/redis/value', methods=['GET'])
def redis_value():
    """获取 Redis 键的值"""
    conn_id = request.args.get('connectionId', type=int)
    key = request.args.get('key')
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        key_type = db.connection.type(key)
        value = None
        if key_type == 'string':
            try:
                value = db.connection.get(key)
            except Exception:
                value = '(binary data)'
        elif key_type == 'hash':
            try:
                value = db.connection.hgetall(key)
            except Exception:
                value = {'(error)': 'binary data'}
        elif key_type == 'list':
            try:
                value = db.connection.lrange(key, 0, -1)
            except Exception:
                value = ['(binary data)']
        elif key_type == 'set':
            try:
                value = list(db.connection.smembers(key))
            except Exception:
                value = ['(binary data)']
        elif key_type == 'zset':
            try:
                value = db.connection.zrange(key, 0, -1, withscores=True)
            except Exception:
                value = []
        return jsonify({'success': True, 'key': key, 'type': key_type, 'value': value})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/redis/command', methods=['POST'])
def redis_command():
    """执行 Redis 命令"""
    data = request.json
    conn_id = data.get('connectionId')
    command = data.get('command', '').strip()
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        import shlex
        parts = shlex.split(command)
        if not parts:
            return jsonify({'success': False, 'error': '命令不能为空'}), 400
        raw = db.connection.execute_command(*parts)
        # 结构化返回: 列表/元组作为数组, 方便前端按列表展示
        def safe(v):
            if isinstance(v, bytes):
                try: return v.decode('utf-8')
                except: return v.hex()
            if isinstance(v, (list, tuple)):
                return [safe(x) for x in v]
            return v
        result = safe(raw)
        return jsonify({'success': True, 'result': result, 'command': command, 'is_list': isinstance(result, list)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/redis/set', methods=['POST'])
def redis_set():
    """设置 Redis 字符串值"""
    data = request.json
    conn_id = data.get('connectionId')
    key = data.get('key')
    value = data.get('value')
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        db.connection.set(key, value)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/redis/delete', methods=['POST'])
def redis_delete():
    """删除 Redis 键"""
    data = request.json
    conn_id = data.get('connectionId')
    key = data.get('key')
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        db.connection.delete(key)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/redis/ttl', methods=['POST'])
def redis_set_ttl():
    """设置 Redis 键过期时间"""
    data = request.json
    conn_id = data.get('connectionId')
    key = data.get('key')
    ttl = data.get('ttl', -1)
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        if ttl < 0:
            db.connection.persist(key)
        else:
            db.connection.expire(key, ttl)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/redis/flushdb', methods=['POST'])
def redis_flushdb():
    """清空当前 Redis 数据库"""
    data = request.json
    conn_id = data.get('connectionId')
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        db.connection.flushdb()
        return jsonify({'success': True, 'message': '当前数据库已清空'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/redis/server-info', methods=['GET'])
def redis_server_info():
    """获取 Redis 服务器信息"""
    conn_id = request.args.get('connectionId', type=int)
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        info = db.connection.info()
        return jsonify({
            'success': True,
            'info': {
                'redis_version': info.get('redis_version', ''),
                'uptime_in_seconds': info.get('uptime_in_seconds', 0),
                'connected_clients': info.get('connected_clients', 0),
                'used_memory_human': info.get('used_memory_human', ''),
                'total_keys': info.get('db0', {}).get('keys', 0) if 'db0' in info else 0,
                'os': info.get('os', ''),
                'arch_bits': info.get('arch_bits', ''),
                'tcp_port': info.get('tcp_port', ''),
                'server_mode': info.get('redis_mode', ''),
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ==================== MongoDB API ====================
@api.route('/mongodb/databases', methods=['GET'])
def mongodb_databases():
    """获取数据库列表"""
    conn_id = request.args.get('connectionId', type=int)
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        databases = db.connection.list_database_names()
        return jsonify({'success': True, 'databases': databases})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/mongodb/collections', methods=['GET'])
def mongodb_collections():
    """获取集合列表"""
    conn_id = request.args.get('connectionId', type=int)
    database = request.args.get('database', '')
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        collections = db.connection[database].list_collection_names()
        return jsonify({'success': True, 'collections': collections})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/mongodb/schema', methods=['GET'])
def mongodb_schema():
    """获取集合字段结构"""
    conn_id = request.args.get('connectionId', type=int)
    database = request.args.get('database', '')
    collection = request.args.get('collection', '')
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        coll = db.connection[database][collection]
        
        # 分析所有文档获取字段
        fields = set()
        total_count = coll.count_documents({})
        
        # 如果数据量太大，分批处理
        batch_size = 1000
        if total_count > 10000:
            # 大数据量时只采样
            sample = list(coll.find().limit(500))
            for doc in sample:
                for key in doc.keys():
                    fields.add(key)
        else:
            # 小数据量时遍历所有文档
            for doc in coll.find():
                for key in doc.keys():
                    fields.add(key)
        
        fields_list = sorted(list(fields))
        
        # 返回字段列表在 header 中
        response = jsonify({'success': True, 'fields': fields_list, 'total': total_count})
        response.headers['X-Mongo-Fields'] = ','.join(fields_list)
        return response
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/mongodb/find', methods=['POST'])
def mongodb_find():
    """查询文档"""
    data = request.json
    conn_id = data.get('connectionId')
    database = data.get('database', '')
    collection = data.get('collection', '')
    query = data.get('query', {})
    limit = data.get('limit', 100)
    skip = data.get('skip', 0)
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        if isinstance(query, str) and query.strip():
            import json
            def parse_json(s):
                if not s or not isinstance(s, str):
                    return {}
                try:
                    return json.loads(s)
                except:
                    s = s.replace("'", '"')
                    return json.loads(s)
            
            query = parse_json(query)
        
        coll = db.connection[database][collection]
        cursor = coll.find(query).skip(skip).limit(limit)
        documents = []
        for doc in cursor:
            doc['_id'] = str(doc.get('_id', ''))
            documents.append(doc)
        
        total = coll.count_documents(query)
        
        # 获取所有字段名（包含 _id）
        all_fields = set()
        for doc in coll.find(query).limit(min(total, 1000)):
            for key in doc.keys():
                all_fields.add(key)
        fields_list = sorted(list(all_fields))
        
        response = jsonify({'success': True, 'documents': documents, 'total': total, 'limit': limit, 'skip': skip})
        response.headers['X-Mongo-Fields'] = ','.join(fields_list)
        return response
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/mongodb/insert', methods=['POST'])
def mongodb_insert():
    """插入文档"""
    data = request.json
    conn_id = data.get('connectionId')
    database = data.get('database', '')
    collection = data.get('collection', '')
    document = data.get('document', {})
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        import json
        if isinstance(document, str) and document.strip():
            try:
                document = json.loads(document)
            except:
                # 转换单引号为双引号
                document = json.loads(document.replace("'", '"'))
        
        coll = db.connection[database][collection]
        if isinstance(document, list):
            result = coll.insert_many(document)
            return jsonify({'success': True, 'inserted_ids': [str(x) for x in result.inserted_ids]})
        else:
            result = coll.insert_one(document)
            return jsonify({'success': True, 'inserted_id': str(result.inserted_id)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/mongodb/update', methods=['POST'])
def mongodb_update():
    """更新文档"""
    data = request.json
    conn_id = data.get('connectionId')
    database = data.get('database', '')
    collection = data.get('collection', '')
    query = data.get('query', {})
    update = data.get('update', {})
    many = data.get('many', False)
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        import json
        import re
        def parse_json(s):
            if not s or not isinstance(s, str):
                return {}
            # 尝试 json.loads, 如果失败则尝试转换单引号为双引号
            try:
                return json.loads(s)
            except:
                # 替换单引号为双引号, 处理 MongoDB 语法
                s = s.replace("'", '"')
                # 处理 $ 开头的键名 (保持为字符串)
                return json.loads(s)
        
        if isinstance(query, str) and query.strip():
            query = parse_json(query)
        if isinstance(update, str) and update.strip():
            update = parse_json(update)
        
        # 转换 _id 为 ObjectId
        from bson import ObjectId
        if '_id' in query and isinstance(query['_id'], str):
            try:
                query['_id'] = ObjectId(query['_id'])
            except:
                pass
        
        coll = db.connection[database][collection]
        if many:
            result = coll.update_many(query, update)
        else:
            result = coll.update_one(query, update)
        return jsonify({'success': True, 'modified_count': result.modified_count, 'matched_count': result.matched_count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/mongodb/delete', methods=['POST'])
def mongodb_delete():
    """删除文档"""
    data = request.json
    conn_id = data.get('connectionId')
    database = data.get('database', '')
    collection = data.get('collection', '')
    query = data.get('query', {})
    many = data.get('many', False)
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        import json
        def parse_json(s):
            if not s or not isinstance(s, str):
                return {}
            try:
                return json.loads(s)
            except:
                s = s.replace("'", '"')
                return json.loads(s)
        
        if isinstance(query, str) and query.strip():
            query = parse_json(query)
        
        # 转换 _id 为 ObjectId
        from bson import ObjectId
        if '_id' in query and isinstance(query['_id'], str):
            try:
                query['_id'] = ObjectId(query['_id'])
            except:
                pass
        
        coll = db.connection[database][collection]
        if many:
            result = coll.delete_many(query)
        else:
            result = coll.delete_one(query)
        return jsonify({'success': True, 'deleted_count': result.deleted_count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/mongodb/server-info', methods=['GET'])
def mongodb_server_info():
    """获取 MongoDB 服务器信息"""
    conn_id = request.args.get('connectionId', type=int)
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        info = db.connection.admin.command('buildInfo')
        return jsonify({'success': True, 'info': {'version': info.get('version', ''), 'gitVersion': info.get('gitVersion', ''), 'maxBsonObjectSize': info.get('maxBsonObjectSize', 0)}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/mongodb/create-database', methods=['POST'])
def mongodb_create_database():
    """创建数据库 (通过创建空集合)"""
    data = request.json
    conn_id = data.get('connectionId')
    database = data.get('database', '')
    collection = data.get('collection', '')
    
    if not database:
        return jsonify({'success': False, 'error': '请指定数据库名称'}), 400
    if not collection:
        return jsonify({'success': False, 'error': '请指定集合名称'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        # 创建一个空集合来创建数据库
        db.connection[database][collection].insert_one({'_temp': True})
        # 删除临时文档
        db.connection[database][collection].delete_one({'_temp': True})
        return jsonify({'success': True, 'message': f'数据库 {database} 创建成功'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/mongodb/indexes', methods=['GET'])
def mongodb_indexes():
    """获取集合索引列表"""
    conn_id = request.args.get('connectionId', type=int)
    database = request.args.get('database', '')
    collection = request.args.get('collection', '')
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        coll = db.connection[database][collection]
        indexes = list(coll.list_indexes())
        # 简化索引信息
        index_list = []
        for idx in indexes:
            index_list.append({
                'name': idx.get('name', ''),
                'key': idx.get('key', {}),
                'unique': idx.get('unique', False),
                'sparse': idx.get('sparse', False),
                'expireAfterSeconds': idx.get('expireAfterSeconds')
            })
        return jsonify({'success': True, 'indexes': index_list})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/mongodb/create-index', methods=['POST'])
def mongodb_create_index():
    """创建索引"""
    data = request.json
    conn_id = data.get('connectionId')
    database = data.get('database', '')
    collection = data.get('collection', '')
    keys = data.get('keys', {})  # 例如: {"name": 1, "age": -1}
    unique = data.get('unique', False)
    name = data.get('name', '')
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        coll = db.connection[database][collection]
        index_keys = {}
        # 解析 keys 字符串
        if isinstance(keys, str):
            import json
            try:
                index_keys = json.loads(keys)
            except:
                keys = keys.replace("'", '"')
                index_keys = json.loads(keys)
        else:
            index_keys = keys
        
        # 构建索引选项
        index_options = {'unique': unique}
        if name:
            index_options['name'] = name
        
        # 创建索引
        result = coll.create_index(list(index_keys.items()), **index_options)
        return jsonify({'success': True, 'index_name': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/mongodb/drop-index', methods=['POST'])
def mongodb_drop_index():
    """删除索引"""
    data = request.json
    conn_id = data.get('connectionId')
    database = data.get('database', '')
    collection = data.get('collection', '')
    index_name = data.get('index_name', '')
    
    if not index_name:
        return jsonify({'success': False, 'error': '请指定索引名称'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        coll = db.connection[database][collection]
        result = coll.drop_index(index_name)
        return jsonify({'success': True, 'message': f'索引 {index_name} 已删除'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api.route('/export/json', methods=['POST'])
def export_json():
    """导出JSON"""
    data = request.json
    conn_id = data.get('connectionId')
    sql = data.get('sql')
    
    if not conn_id or not sql:
        return jsonify({'success': False, 'error': '缺少参数'}), 400
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接数据库'}), 400
    
    result = db.execute_sql(sql)
    if not result['success']:
        return jsonify(result)
    
    import json
    json_content = json.dumps(result['data'], ensure_ascii=False, default=str)
    
    return jsonify({
        'success': True,
        'type': 'json',
        'content': json_content,
        'rowCount': result['rowCount']
    })
