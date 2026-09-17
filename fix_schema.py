import re

with open(r'D:\work\pyNDB\api\routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the broken function and replace it
old = r"@api\.route\('/mongodb/schema', methods=\['GET'\]\)\ndef mongodb_schema\(\):.*?return jsonify\(\{'success': False, 'error': str\(e\)\}\), 400"

new = """@api.route('/mongodb/schema', methods=['GET'])
def mongodb_schema():
    \"\"\"获取集合字段结构\"\"\"
    conn_id = request.args.get('connectionId', type=int)
    database = request.args.get('database', '')
    collection = request.args.get('collection', '')
    
    db = get_active_connection(conn_id)
    if not db:
        return jsonify({'success': False, 'error': '未连接'}), 400
    try:
        coll = db.connection[database][collection]
        sample = list(coll.find().limit(100))
        
        fields = set()
        for doc in sample:
            for key in doc.keys():
                if key != '_id':
                    fields.add(key)
        
        return jsonify({'success': True, 'fields': sorted(list(fields))})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400"""

content = re.sub(old, new, content, flags=re.DOTALL)

with open(r'D:\work\pyNDB\api\routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
