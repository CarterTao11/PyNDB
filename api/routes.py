"""
API 路由
"""
import time
from flask import Blueprint, request, jsonify, session
from models.database import ConnectionModel, QueryHistoryModel
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
    
    required = ['name', 'db_type', 'host', 'port', 'username', 'database_name']
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
