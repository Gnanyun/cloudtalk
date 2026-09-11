
from flask import Flask, request, jsonify, send_from_directory, Response, session
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image  # 需要 pip install Pillow
from functools import wraps

app = Flask(__name__, static_folder='static', static_url_path='/static')

# ==================== 安全配置（补丁一新增，全部为增量）====================

# SECRET_KEY（用于会话签名，防止会话伪造）
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# 会话 Cookie 安全属性
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('FLASK_ENV') == 'production':
    app.config['SESSION_COOKIE_SECURE'] = True

# 文件上传 MIME 白名单（补充扩展名校验）
ALLOWED_MIMES = {'image/png', 'image/jpeg', 'image/gif'}

def verify_image(filepath):
    """用 Pillow 验证文件确实是合法图片"""
    try:
        with Image.open(filepath) as img:
            img.verify()
        return True
    except Exception:
        return False

# ==================== 安全配置结束 ====================
# ---------- 配置文件上传 ----------
UPLOAD_FOLDER = os.path.join('static', 'uploads', 'avatars')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 限制 5MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------- 数据库初始化 ----------
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    # =====  新增：管理员表（放在最前面）=====
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )''')

    # =====  新增：插入默认管理员 =====
    c.execute("SELECT COUNT(*) FROM admins")
    if c.fetchone()[0] == 0:
        hashed = generate_password_hash('admin123')
        c.execute("INSERT INTO admins (username, password) VALUES (?, ?)", ('admin', hashed))

    # 用户表
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # 检查并添加 avatar 字段
    c.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in c.fetchall()]
    if 'avatar' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT ''")

    # 帖子表
    c.execute('''CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        author TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        views INTEGER DEFAULT 0,
        likes INTEGER DEFAULT 0,
        comments INTEGER DEFAULT 0
    )''')

    # 插入示例帖子
    c.execute('SELECT COUNT(*) FROM posts')
    if c.fetchone()[0] == 0:
        sample_posts = [
            ('前端开发新趋势：2024年值得关注的技术',
             '随着Web技术的快速发展，前端领域每年都会涌现出新的框架和工具...',
             '技术先锋', 2300, 248, 136),
            ('我的极简租房改造：用百元预算打造温馨小窝',
             '作为一名租房党，一直想把自己的小窝改造得温馨又舒适...',
             '生活美学', 1800, 312, 98),
            ('新手入门PS：从零开始的设计学习路线',
             '很多想学设计的朋友都问我，新手怎么入门PS？...',
             '创意达人', 2100, 275, 156)
        ]
        c.executemany('INSERT INTO posts (title, content, author, views, likes, comments) VALUES (?,?,?,?,?,?)',
                      sample_posts)

    # 分类表
    c.execute('''CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(username, name)
    )''')
    
    # 插入默认分类
    default_categories = ['技术', '创意', '生活', '问答', '其他']
    for cat in default_categories:
        c.execute('INSERT OR IGNORE INTO categories (username, name) VALUES (?, ?)', ('system', cat))

    # 检查并添加 category 字段
    c.execute("PRAGMA table_info(posts)")
    columns = [col[1] for col in c.fetchall()]
    if 'category' not in columns:
        c.execute("ALTER TABLE posts ADD COLUMN category TEXT DEFAULT '其他'")

    # 检查并添加 tags 字段
    c.execute("PRAGMA table_info(posts)")
    columns = [col[1] for col in c.fetchall()]
    if 'tags' not in columns:
        c.execute("ALTER TABLE posts ADD COLUMN tags TEXT DEFAULT '其他'")

    # 签到表
    c.execute('''CREATE TABLE IF NOT EXISTS checkins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        checkin_date TEXT NOT NULL,
        UNIQUE(username, checkin_date)
    )''')

    # 用户花朵表
    c.execute('''CREATE TABLE IF NOT EXISTS user_flowers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        flower_name TEXT NOT NULL,
        flower_emoji TEXT NOT NULL,
        rarity TEXT NOT NULL,
        obtained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # 公告表
    c.execute('''CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        media_type TEXT DEFAULT 'text',
        media_url TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # ===== 新增：群组表 =====
    c.execute('''CREATE TABLE IF NOT EXISTS groups_info (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT '',
        creator TEXT NOT NULL,
        avatar TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # ===== 新增：群组成员表 =====
    c.execute('''CREATE TABLE IF NOT EXISTS group_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        role TEXT DEFAULT 'member',
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(group_id, username),
        FOREIGN KEY (group_id) REFERENCES groups_info(id)
    )''')

    # ===== 插入默认群组 =====
    c.execute("SELECT COUNT(*) FROM groups_info")
    if c.fetchone()[0] == 0:
        sample_groups = [
            ('技术交流群', '讨论编程、技术相关话题', '技术先锋'),
            ('设计创意群', '分享设计作品和创意灵感', '创意达人'),
            ('生活分享群', '分享生活趣事和经验', '生活美学家')
        ]
        for name, desc, creator in sample_groups:
            c.execute(
                'INSERT INTO groups_info (name, description, creator) VALUES (?, ?, ?)',
                (name, desc, creator)
            )
            # 创建者自动成为管理员
            group_id = c.lastrowid
            c.execute(
                'INSERT INTO group_members (group_id, username, role) VALUES (?, ?, ?)',
                (group_id, creator, 'admin')
            )
            # 添加一些默认成员
            for member in ['技术先锋', '创意达人', '生活美学家']:
                if member != creator:
                    try:
                        c.execute(
                            'INSERT INTO group_members (group_id, username) VALUES (?, ?)',
                            (group_id, member)
                        )
                    except:
                        pass

    conn.commit()
    conn.close()

init_db()

# ---------- 数据库连接 ----------
def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# ---------- 管理端鉴权装饰器 ----------
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_token'):
            return jsonify({'status': 'error', 'msg': '未登录或登录已过期'}), 401
        return f(*args, **kwargs)
    return decorated

# ---------- 生成默认头像 API ----------
@app.route('/api/default-avatar')
def default_avatar():
    """生成基于用户名首字母的彩色默认头像"""
    username = request.args.get('name', 'User')
    initial = username[0].upper() if username else 'U'
    
    # 根据用户名生成固定的颜色
    hash_val = int(hashlib.md5(username.encode()).hexdigest()[:8], 16)
    hue = hash_val % 360
    
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="50" fill="hsl({hue}, 70%, 60%)"/>
        <text x="50" y="70" font-size="50" font-family="Arial, sans-serif" font-weight="bold" 
              fill="white" text-anchor="middle" dominant-baseline="middle">{initial}</text>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml')

# ---------- 首页 ----------
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

# ---------- 话题页面 ----------
@app.route('/topic')
def topic_page():
    return send_from_directory('static', 'topic.html')

# ---------- 注册 ----------
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'status': 'error', 'msg': '用户名和密码不能为空'}), 400

    hashed = generate_password_hash(password)
    try:
        conn = get_db()
        conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'msg': '注册成功'})
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'msg': '用户名已存在'}), 409

# ---------- 登录 ----------
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'status': 'error', 'msg': '用户名和密码不能为空'}), 400

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user['password'], password):
        return jsonify({'status': 'error', 'msg': '用户名或密码错误'}), 401

    return jsonify({
        'status': 'success',
        'msg': '登录成功',
        'user': {
            'id': user['id'],
            'username': user['username'],
            'avatar': user['avatar'] or f'/api/default-avatar?name={username}'
        }
    })

# ---------- 获取所有帖子 ----------
@app.route('/api/posts', methods=['GET'])
def get_posts():
    conn = get_db()
    try:
        conn.execute("ALTER TABLE posts ADD COLUMN hidden INTEGER DEFAULT 0")
    except:
        pass
    posts = conn.execute(
        'SELECT * FROM posts WHERE (hidden IS NULL OR hidden = 0) ORDER BY created_at DESC'
    ).fetchall()
    conn.close()
    result = []
    for post in posts:
        post_dict = dict(post)
        # 查询作者头像
        conn = get_db()
        author = conn.execute('SELECT avatar FROM users WHERE username = ?', 
                              (post_dict['author'],)).fetchone()
        conn.close()
        
        if author and author['avatar']:
            post_dict['author_avatar'] = author['avatar']
        else:
            post_dict['author_avatar'] = f'/api/default-avatar?name={post_dict["author"]}'
        
        result.append(post_dict)
    
    return jsonify(result)

# ---------- 发布帖子 ----------

# ---------- 头像上传 ----------
@app.route('/api/upload-avatar', methods=['POST'])
def upload_avatar():
    username = request.form.get('username')
    if not username:
        return jsonify({'status': 'error', 'msg': '请先登录'}), 401

    if 'avatar' not in request.files:
        return jsonify({'status': 'error', 'msg': '没有选择文件'}), 400

    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'status': 'error', 'msg': '文件名为空'}), 400

    if not allowed_file(file.filename):
        return jsonify({'status': 'error', 'msg': '仅支持 png, jpg, jpeg, gif 格式'}), 400

    # 生成唯一文件名
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    try:
        file.save(filepath)
    except Exception as e:
        return jsonify({'status': 'error', 'msg': f'保存文件失败: {str(e)}'}), 500

    # 更新数据库中的头像路径
    avatar_url = f"/static/uploads/avatars/{filename}"
    conn = get_db()
    conn.execute('UPDATE users SET avatar = ? WHERE username = ?', (avatar_url, username))
    conn.commit()
    conn.close()

    return jsonify({'status': 'success', 'msg': '头像上传成功', 'avatar_url': avatar_url})

# ---------- 获取话题详情 ----------
@app.route('/api/topic/<int:topic_id>', methods=['GET'])
def get_topic(topic_id):
    conn = get_db()
    topic = conn.execute('SELECT * FROM posts WHERE id = ?', (topic_id,)).fetchone()
    
    if not topic:
        conn.close()
        return jsonify({'status': 'error', 'msg': '话题不存在'}), 404
    
    topic_dict = dict(topic)
    
    # 获取作者头像
    author = conn.execute('SELECT avatar FROM users WHERE username = ?', 
                          (topic_dict['author'],)).fetchone()
    if author and author['avatar']:
        topic_dict['author_avatar'] = author['avatar']
    else:
        topic_dict['author_avatar'] = f'/api/default-avatar?name={topic_dict["author"]}'
    
    # 获取作者统计
    author_posts = conn.execute('SELECT COUNT(*) FROM posts WHERE author = ?', 
                                (topic_dict['author'],)).fetchone()[0]
    
    # 获取作者获赞总数
    author_likes_result = conn.execute(
        'SELECT SUM(likes) FROM posts WHERE author = ?', 
        (topic_dict['author'],)
    ).fetchone()
    author_likes = author_likes_result[0] if author_likes_result and author_likes_result[0] else 0
    
    # 确保关注表存在并获取粉丝数
    conn.execute('''CREATE TABLE IF NOT EXISTS follows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        follower TEXT NOT NULL,
        following TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(follower, following)
    )''')
    
    followers_count = conn.execute(
        'SELECT COUNT(*) FROM follows WHERE following = ?',
        (topic_dict['author'],)
    ).fetchone()[0]
    
    topic_dict['author_posts'] = author_posts
    topic_dict['author_followers'] = followers_count
    topic_dict['author_likes'] = author_likes
    topic_dict['tags'] = ['技术', '分享']
    topic_dict['is_following'] = False
    
    # 相关推荐 - 随机获取5篇其他帖子
    related = conn.execute(
        'SELECT id, title, author, views FROM posts WHERE id != ? ORDER BY RANDOM() LIMIT 5',
        (topic_id,)
    ).fetchall()
    topic_dict['related'] = [dict(p) for p in related]
    
    conn.close()
    return jsonify({'status': 'success', 'topic': topic_dict})

# ---------- 增加浏览量 ----------
@app.route('/api/topic/<int:topic_id>/view', methods=['POST'])
def increase_view(topic_id):
    conn = get_db()
    conn.execute('UPDATE posts SET views = views + 1 WHERE id = ?', (topic_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

# ---------- 点赞话题 ----------
@app.route('/api/topic/<int:topic_id>/like', methods=['POST'])
def like_topic(topic_id):
    data = request.get_json()
    username = data.get('username')
    
    if not username:
        return jsonify({'status': 'error', 'msg': '请先登录'}), 401
    
    conn = get_db()
    
    # 创建点赞表
    conn.execute('''CREATE TABLE IF NOT EXISTS post_likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(post_id, username)
    )''')
    
    # 检查是否已点赞
    existing = conn.execute(
        'SELECT id FROM post_likes WHERE post_id = ? AND username = ?',
        (topic_id, username)
    ).fetchone()
    
    if existing:
        # 取消点赞
        conn.execute('DELETE FROM post_likes WHERE post_id = ? AND username = ?',
                    (topic_id, username))
        conn.execute('UPDATE posts SET likes = likes - 1 WHERE id = ?', (topic_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'action': 'unliked'})
    else:
        # 点赞
        conn.execute('INSERT INTO post_likes (post_id, username) VALUES (?, ?)',
                    (topic_id, username))
        conn.execute('UPDATE posts SET likes = likes + 1 WHERE id = ?', (topic_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'action': 'liked'})

# ---------- 获取评论 ----------
@app.route('/api/topic/<int:topic_id>/comments', methods=['GET'])
def get_comments(topic_id):
    conn = get_db()
    
    # 创建评论表（如果不存在）
    conn.execute('''CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        author TEXT NOT NULL,
        content TEXT NOT NULL,
        likes INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    
    comments = conn.execute(
        'SELECT * FROM comments WHERE post_id = ? ORDER BY created_at DESC',
        (topic_id,)
    ).fetchall()
    
    result = []
    for c in comments:
        comment = dict(c)
        # 检查是否是作者
        post = conn.execute('SELECT author FROM posts WHERE id = ?', (topic_id,)).fetchone()
        comment['is_author'] = (post and comment['author'] == post['author'])
        
        # 获取评论者头像
        user = conn.execute('SELECT avatar FROM users WHERE username = ?', 
                            (comment['author'],)).fetchone()
        if user and user['avatar']:
            comment['avatar'] = user['avatar']
        else:
            comment['avatar'] = f'/api/default-avatar?name={comment["author"]}'
        
        result.append(comment)
    
    conn.close()
    return jsonify(result)

# ---------- 发表评论 ----------
@app.route('/api/topic/<int:topic_id>/comments', methods=['POST'])
def add_comment(topic_id):
    data = request.get_json()
    author = data.get('author')
    content = data.get('content')
    
    if not author or not content:
        return jsonify({'status': 'error', 'msg': '评论内容不能为空'}), 400
    
    conn = get_db()
    
    # 确保评论表存在
    conn.execute('''CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        author TEXT NOT NULL,
        content TEXT NOT NULL,
        likes INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    try:
        conn.execute(
            'INSERT INTO comments (post_id, author, content) VALUES (?, ?, ?)',
            (topic_id, author, content)
        )
        
        # 更新帖子的评论数
        conn.execute('UPDATE posts SET comments = comments + 1 WHERE id = ?', (topic_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'status': 'success', 'msg': '评论成功'})
    except Exception as e:
        conn.close()
        return jsonify({'status': 'error', 'msg': f'评论失败: {str(e)}'}), 500

# ---------- 关注用户 ----------
@app.route('/api/user/follow', methods=['POST'])
def follow_user():
    data = request.get_json()
    follower = data.get('follower')
    following = data.get('following')
    
    if not follower or not following:
        return jsonify({'status': 'error', 'msg': '参数错误'}), 400
    
    # 不能关注自己
    if follower == following:
        return jsonify({'status': 'error', 'msg': '不能关注自己'}), 400
    
    conn = get_db()
    
    # 创建关注表
    conn.execute('''CREATE TABLE IF NOT EXISTS follows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        follower TEXT NOT NULL,
        following TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(follower, following)
    )''')
    
    try:
        conn.execute('INSERT INTO follows (follower, following) VALUES (?, ?)',
                    (follower, following))
        conn.commit()
        return jsonify({'status': 'success', 'msg': '关注成功', 'action': 'followed'})
    except sqlite3.IntegrityError:
        # 已关注，取消关注
        conn.execute('DELETE FROM follows WHERE follower = ? AND following = ?',
                    (follower, following))
        conn.commit()
        return jsonify({'status': 'success', 'msg': '取消关注', 'action': 'unfollowed'})
    finally:
        conn.close()

# ---------- 获取热门帖子（按浏览量排序） ----------
@app.route('/api/posts/hot', methods=['GET'])
def get_hot_posts():
    conn = get_db()
    try:
        conn.execute("ALTER TABLE posts ADD COLUMN hidden INTEGER DEFAULT 0")
    except:
        pass
    posts = conn.execute(
        'SELECT * FROM posts WHERE (hidden IS NULL OR hidden = 0) ORDER BY views DESC, likes DESC LIMIT 20'
    ).fetchall()
    conn.close()
    
    result = []
    for post in posts:
        post_dict = dict(post)
        conn = get_db()
        author = conn.execute('SELECT avatar FROM users WHERE username = ?', 
                              (post_dict['author'],)).fetchone()
        conn.close()
        
        if author and author['avatar']:
            post_dict['author_avatar'] = author['avatar']
        else:
            post_dict['author_avatar'] = f'/api/default-avatar?name={post_dict["author"]}'
        
        result.append(post_dict)
    
    return jsonify(result)

# ---------- 获取精华帖子（按点赞数排序） ----------
@app.route('/api/posts/featured', methods=['GET'])
def get_featured_posts():
    conn = get_db()
    try:
        conn.execute("ALTER TABLE posts ADD COLUMN hidden INTEGER DEFAULT 0")
    except:
        pass
    posts = conn.execute(
        'SELECT * FROM posts WHERE (hidden IS NULL OR hidden = 0) ORDER BY likes DESC, comments DESC LIMIT 20'
    ).fetchall()
    conn.close()
    
    result = []
    for post in posts:
        post_dict = dict(post)
        conn = get_db()
        author = conn.execute('SELECT avatar FROM users WHERE username = ?', 
                              (post_dict['author'],)).fetchone()
        conn.close()
        
        if author and author['avatar']:
            post_dict['author_avatar'] = author['avatar']
        else:
            post_dict['author_avatar'] = f'/api/default-avatar?name={post_dict["author"]}'
        
        result.append(post_dict)
    
    return jsonify(result)

# ---------- 按分类获取帖子 ----------
@app.route('/api/posts/category/<category>', methods=['GET'])
def get_posts_by_category(category):
    conn = get_db()
    
    if category == 'all':
        posts = conn.execute(
            'SELECT * FROM posts WHERE (hidden IS NULL OR hidden = 0) ORDER BY created_at DESC'
        ).fetchall()
    else:
        posts = conn.execute(
            "SELECT * FROM posts WHERE (hidden IS NULL OR hidden = 0) AND (tags LIKE ? OR category LIKE ?) ORDER BY created_at DESC",
            (f'%{category}%', f'%{category}%')
        ).fetchall()
    
    conn.close()
    
    result = []
    for post in posts:
        post_dict = dict(post)
        conn = get_db()
        author = conn.execute('SELECT avatar FROM users WHERE username = ?', 
                              (post_dict['author'],)).fetchone()
        conn.close()
        
        if author and author['avatar']:
            post_dict['author_avatar'] = author['avatar']
        else:
            post_dict['author_avatar'] = f'/api/default-avatar?name={post_dict["author"]}'
        
        result.append(post_dict)
    
    return jsonify(result)

# ---------- 搜索帖子 ----------
@app.route('/api/posts/search', methods=['GET'])
def search_posts():
    keyword = request.args.get('q', '').strip()
    
    if not keyword:
        return jsonify([])
    
    conn = get_db()
    search_pattern = f'%{keyword}%'
    posts = conn.execute(
    '''SELECT * FROM posts 
       WHERE (hidden IS NULL OR hidden = 0) 
       AND (title LIKE ? OR content LIKE ? OR author LIKE ?)
       ORDER BY created_at DESC''',
    (search_pattern, search_pattern, search_pattern)
).fetchall()
    conn.close()
    
    result = []
    for post in posts:
        post_dict = dict(post)
        conn = get_db()
        author = conn.execute('SELECT avatar FROM users WHERE username = ?', 
                              (post_dict['author'],)).fetchone()
        conn.close()
        
        if author and author['avatar']:
            post_dict['author_avatar'] = author['avatar']
        else:
            post_dict['author_avatar'] = f'/api/default-avatar?name={post_dict["author"]}'
        
        result.append(post_dict)
    
    return jsonify(result)

# ---------- 页面路由 ----------
@app.route('/profile')
def profile_page():
    return send_from_directory('static', 'profile.html')

@app.route('/notifications')
def notifications_page():
    return send_from_directory('static', 'notifications.html')

@app.route('/settings')
def settings_page():
    return send_from_directory('static', 'settings.html')

# ---------- 获取用户的帖子/评论/点赞/关注 ----------
@app.route('/api/user/<username>/<tab>', methods=['GET'])
def get_user_tab_content(username, tab):
    conn = get_db()
    result = []
    
    if tab == 'posts':
        try:
            conn.execute("ALTER TABLE posts ADD COLUMN hidden INTEGER DEFAULT 0")
        except:
            pass
        viewer = request.args.get('viewer', '')
        if viewer == username:
            posts = conn.execute(
                'SELECT * FROM posts WHERE author = ? ORDER BY created_at DESC',
                (username,)
            ).fetchall()
        else:
            posts = conn.execute(
                'SELECT * FROM posts WHERE author = ? AND (hidden IS NULL OR hidden = 0) ORDER BY created_at DESC',
                (username,)
            ).fetchall()
        result = [dict(p) for p in posts]
    elif tab == 'comments':
        conn.execute('''CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        comments = conn.execute(
            'SELECT * FROM comments WHERE author = ? ORDER BY created_at DESC',
            (username,)
        ).fetchall()
        result = [dict(c) for c in comments]
    elif tab == 'likes':
        conn.execute('''CREATE TABLE IF NOT EXISTS post_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        posts = conn.execute(
            '''SELECT p.* FROM posts p 
               JOIN post_likes pl ON p.id = pl.post_id 
               WHERE pl.username = ? ORDER BY pl.created_at DESC''',
            (username,)
        ).fetchall()
        result = [dict(p) for p in posts]
    elif tab == 'follows':
        conn.execute('''CREATE TABLE IF NOT EXISTS follows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            follower TEXT NOT NULL,
            following TEXT NOT NULL
        )''')
        follows = conn.execute(
            'SELECT following as username FROM follows WHERE follower = ?',
            (username,)
        ).fetchall()
        for f in follows:
            user = conn.execute('SELECT avatar FROM users WHERE username = ?', (f['username'],)).fetchone()
            result.append({
                'username': f['username'],
                'avatar': user['avatar'] if user else f'/api/default-avatar?name={f["username"]}'
            })
    
    conn.close()
    return jsonify(result)

# ---------- 获取用户分类列表 ----------
@app.route('/api/categories', methods=['GET'])
def get_categories():
    username = request.args.get('username', 'system')
    conn = get_db()
    
    # 获取系统分类和用户自定义分类
    categories = conn.execute(
        'SELECT name FROM categories WHERE username = ? OR username = ? ORDER BY id',
        ('system', username)
    ).fetchall()
    conn.close()
    
    return jsonify([c['name'] for c in categories])

# ---------- 添加自定义分类 ----------
@app.route('/api/categories', methods=['POST'])
def add_category():
    data = request.get_json()
    username = data.get('username')
    name = data.get('name', '').strip()
    
    if not username or not name:
        return jsonify({'status': 'error', 'msg': '参数错误'}), 400
    
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO categories (username, name) VALUES (?, ?)',
            (username, name)
        )
        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'msg': '分类添加成功'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'status': 'error', 'msg': '该分类已存在'}), 409

# ---------- 修改发布帖子API，支持分类 ----------
# 找到原有的 create_post 函数，修改为：

@app.route('/api/posts', methods=['POST'])
def create_post():
    data = request.get_json()
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    author = data.get('author', '').strip()
    tags = data.get('tags', '其他').strip()

    if not title or not content or not author:
        return jsonify({'status': 'error', 'msg': '标题、内容和作者不能为空'}), 400

    conn = get_db()
    cursor = conn.execute(
        'INSERT INTO posts (title, content, author, tags) VALUES (?, ?, ?, ?)',
        (title, content, author, tags)
    )
    conn.commit()
    post_id = cursor.lastrowid
    conn.close()

    return jsonify({'status': 'success', 'msg': '发布成功', 'postId': post_id})

# ---------- 删除帖子 ----------
@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
def delete_post(post_id):
    data = request.get_json()
    username = data.get('username', '')
    
    if not username:
        return jsonify({'status': 'error', 'msg': '请先登录'}), 401
    
    conn = get_db()
    post = conn.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    
    if not post:
        conn.close()
        return jsonify({'status': 'error', 'msg': '帖子不存在'}), 404
    
    if post['author'] != username:
        conn.close()
        return jsonify({'status': 'error', 'msg': '只能删除自己的帖子'}), 403
    
    # 确保表存在
    conn.execute('''CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        author TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS post_likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 删除相关评论和点赞
    conn.execute('DELETE FROM comments WHERE post_id = ?', (post_id,))
    conn.execute('DELETE FROM post_likes WHERE post_id = ?', (post_id,))
    # 删除帖子
    conn.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'success', 'msg': '删除成功'})

# ---------- 签到 ----------
@app.route('/api/checkin', methods=['POST'])
def checkin():
    data = request.get_json()
    username = data.get('username', '')
    
    if not username:
        return jsonify({'status': 'error', 'msg': '请先登录'}), 401
    
    from datetime import date
    today = date.today().isoformat()
    
    conn = get_db()
    
    # 检查今天是否已签到
    existing = conn.execute(
        'SELECT id FROM checkins WHERE username = ? AND checkin_date = ?',
        (username, today)
    ).fetchone()
    
    if existing:
        conn.close()
        return jsonify({'status': 'error', 'msg': '今天已经签到过了'})
    
    # 签到
    conn.execute('INSERT INTO checkins (username, checkin_date) VALUES (?, ?)',
                (username, today))
    
    # 计算连续签到天数
    all_checkins = conn.execute(
        'SELECT checkin_date FROM checkins WHERE username = ? ORDER BY checkin_date DESC LIMIT 10',
        (username,)
    ).fetchall()
    
    dates = [c['checkin_date'] for c in all_checkins]
    consecutive = 1
    for i in range(len(dates) - 1):
        from datetime import timedelta
        d1 = date.fromisoformat(dates[i])
        d2 = date.fromisoformat(dates[i + 1])
        if (d1 - d2).days == 1:
            consecutive += 1
        else:
            break
    
    conn.commit()
    
    can_draw = consecutive >= 3
    conn.close()
    
    return jsonify({
        'status': 'success',
        'msg': '签到成功',
        'consecutive': consecutive,
        'can_draw': can_draw
    })

# ---------- 抽花 ----------
@app.route('/api/draw-flower', methods=['POST'])
def draw_flower():
    import random
    from datetime import date, timedelta
    data = request.get_json()
    username = data.get('username', '')
    
    if not username:
        return jsonify({'status': 'error', 'msg': '请先登录'}), 401
    
    today = date.today()
    today_str = today.isoformat()
    
    conn = get_db()
    
    # 检查今天是否已签到
    today_checkin = conn.execute(
        'SELECT id FROM checkins WHERE username = ? AND checkin_date = ?',
        (username, today_str)
    ).fetchone()
    
    if not today_checkin:
        conn.close()
        return jsonify({'status': 'error', 'msg': '请先签到后再抽花'})
    
    # 计算连续签到天数
    all_checkins = conn.execute(
        'SELECT checkin_date FROM checkins WHERE username = ? ORDER BY checkin_date DESC LIMIT 10',
        (username,)
    ).fetchall()
    
    dates = [c['checkin_date'] for c in all_checkins]
    consecutive = 1
    for i in range(len(dates) - 1):
        d1 = date.fromisoformat(dates[i])
        d2 = date.fromisoformat(dates[i + 1])
        if (d1 - d2).days == 1:
            consecutive += 1
        else:
            break
    
    # 需要连续签到3天才能抽花
    if consecutive < 3:
        conn.close()
        return jsonify({
            'status': 'error', 
            'msg': f'需要连续签到3天才能抽花，当前连续签到 {consecutive} 天'
        })
    
    # 检查今天已抽次数
    draw_count = conn.execute(
        "SELECT COUNT(*) as count FROM user_flowers WHERE username = ? AND obtained_at LIKE ?",
        (username, f'{today_str}%')
    ).fetchone()['count']
    
    if draw_count >= 3:
        conn.close()
        return jsonify({'status': 'error', 'msg': '今天的3次抽花机会已用完'})
    
    # 花朵配置
    flowers = [
        {'name': '向日葵', 'emoji': '🌻', 'rarity': '常见', 'weight': 40},
        {'name': '玫瑰', 'emoji': '🌹', 'rarity': '常见', 'weight': 30},
        {'name': '郁金香', 'emoji': '🌷', 'rarity': '常见', 'weight': 20},
        {'name': '樱花', 'emoji': '🌸', 'rarity': '稀有', 'weight': 8},
        {'name': '蓝玫瑰', 'emoji': '💙', 'rarity': '传说', 'weight': 2}
    ]
    
    total_weight = sum(f['weight'] for f in flowers)
    rand = random.randint(1, total_weight)
    cumulative = 0
    chosen = flowers[0]
    for f in flowers:
        cumulative += f['weight']
        if rand <= cumulative:
            chosen = f
            break
    
    conn.execute(
        'INSERT INTO user_flowers (username, flower_name, flower_emoji, rarity) VALUES (?, ?, ?, ?)',
        (username, chosen['name'], chosen['emoji'], chosen['rarity'])
    )
    conn.commit()
    
    remaining = 2 - draw_count
    conn.close()
    
    return jsonify({
        'status': 'success',
        'flower': chosen,
        'remaining': remaining
    })

# ---------- 获取签到状态 ----------
@app.route('/api/checkin/status/<username>', methods=['GET'])
def get_checkin_status(username):
    from datetime import date, timedelta
    today = date.today()
    today_str = today.isoformat()
    
    conn = get_db()
    
    today_checkin = conn.execute(
        'SELECT id FROM checkins WHERE username = ? AND checkin_date = ?',
        (username, today_str)
    ).fetchone()
    
    all_checkins = conn.execute(
        'SELECT checkin_date FROM checkins WHERE username = ? ORDER BY checkin_date DESC LIMIT 10',
        (username,)
    ).fetchall()
    
    dates = [c['checkin_date'] for c in all_checkins]
    consecutive = 0
    if dates:
        consecutive = 1
        for i in range(len(dates) - 1):
            d1 = date.fromisoformat(dates[i])
            d2 = date.fromisoformat(dates[i + 1])
            if (d1 - d2).days == 1:
                consecutive += 1
            else:
                break
    
    draw_count = conn.execute(
        "SELECT COUNT(*) as count FROM user_flowers WHERE username = ? AND obtained_at LIKE ?",
        (username, f'{today_str}%')
    ).fetchone()['count']
    
    # 需要连续签到3天才能抽花
    can_draw = today_checkin is not None and consecutive >= 3
    remaining = max(0, 3 - draw_count) if can_draw else 0
    
    conn.close()
    
    return jsonify({
        'checked_today': today_checkin is not None,
        'consecutive': consecutive,
        'can_draw': can_draw,
        'remaining': remaining
    })

# ---------- 获取用户花朵 ----------
@app.route('/api/user/flowers/<username>', methods=['GET'])
def get_user_flowers(username):
    conn = get_db()
    flowers = conn.execute(
        'SELECT * FROM user_flowers WHERE username = ? ORDER BY obtained_at DESC',
        (username,)
    ).fetchall()
    conn.close()
    return jsonify([dict(f) for f in flowers])

# ---------- 重置签到（临时） ----------
@app.route('/api/reset-checkin/<username>', methods=['POST'])
def reset_checkin(username):
    conn = get_db()
    conn.execute('DELETE FROM checkins WHERE username = ?', (username,))
    conn.execute('DELETE FROM user_flowers WHERE username = ?', (username,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'msg': '已重置'})

# ---------- 更新用户资料 ----------
@app.route('/api/user/profile/<username>', methods=['PUT'])
def update_user_profile(username):
    data = request.get_json()
    bio = data.get('bio', '').strip()
    avatar = data.get('avatar', '').strip()
    
    conn = get_db()
    
    # 检查用户是否存在
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'status': 'error', 'msg': '用户不存在'}), 404
    
    # 更新 bio 字段
    try:
        conn.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT '这个人很懒，什么都没写~'")
    except:
        pass
    
    if bio:
        conn.execute('UPDATE users SET bio = ? WHERE username = ?', (bio, username))
    
    if avatar:
        conn.execute('UPDATE users SET avatar = ? WHERE username = ?', (avatar, username))
    
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'success', 'msg': '资料更新成功'})

# ---------- 隐藏帖子 ----------
@app.route('/api/posts/<int:post_id>/hide', methods=['GET', 'POST'])
def hide_post(post_id):
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username', '')
    else:
        username = request.args.get('username', '')
    
    conn = get_db()
    post = conn.execute('SELECT * FROM posts WHERE id = ? AND author = ?', (post_id, username)).fetchone()
    
    if not post:
        conn.close()
        return jsonify({'status': 'error', 'msg': '无权操作'}), 403
    
    # 添加 hidden 字段
    try:
        conn.execute("ALTER TABLE posts ADD COLUMN hidden INTEGER DEFAULT 0")
    except:
        pass
    
    # 切换隐藏状态
    new_status = 1 if post['hidden'] == 0 else 0
    conn.execute('UPDATE posts SET hidden = ? WHERE id = ?', (new_status, post_id))
    conn.commit()
    conn.close()
    
    return jsonify({
        'status': 'success', 
        'msg': '帖子已隐藏' if new_status == 1 else '帖子已公开',
        'hidden': new_status == 1
    })

# ---------- 获取用户资料（增强版） ----------
@app.route('/api/user/profile/<username>', methods=['GET'])
def get_user_profile(username):
    conn = get_db()
    
    # 基本信息
    posts_count = conn.execute('SELECT COUNT(*) FROM posts WHERE author = ?', (username,)).fetchone()[0]
    followers_count = conn.execute('SELECT COUNT(*) FROM follows WHERE following = ?', (username,)).fetchone()[0]
    following_count = conn.execute('SELECT COUNT(*) FROM follows WHERE follower = ?', (username,)).fetchone()[0]
    likes_result = conn.execute('SELECT SUM(likes) FROM posts WHERE author = ?', (username,)).fetchone()
    likes_count = likes_result[0] if likes_result[0] else 0
    
    # 获取 bio
    try:
        conn.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT '这个人很懒，什么都没写~'")
    except:
        pass
    
    user = conn.execute('SELECT bio, avatar FROM users WHERE username = ?', (username,)).fetchone()
    bio = user['bio'] if user and user['bio'] else '这个人很懒，什么都没写~'
    avatar = user['avatar'] if user and user['avatar'] else ''
    
    conn.close()
    
    return jsonify({
        'status': 'success',
        'profile': {
            'posts': posts_count,
            'followers': followers_count,
            'following': following_count,
            'likes': likes_count,
            'bio': bio,
            'avatar': avatar
        }
    })

# ---------- 获取用户的帖子（个人中心专用） ----------
@app.route('/api/user/<username>/posts', methods=['GET'])
def get_user_posts_personal(username):
    conn = get_db()
    
    try:
        conn.execute("ALTER TABLE posts ADD COLUMN hidden INTEGER DEFAULT 0")
    except:
        pass
    
    # 获取当前登录用户信息
    current_user = request.args.get('current_user', '')
    
    # 如果是查看自己的帖子，显示所有帖子（包括隐藏的）；否则只显示未隐藏的
    if current_user == username:
        posts = conn.execute(
            'SELECT * FROM posts WHERE author = ? ORDER BY created_at DESC',
            (username,)
        ).fetchall()
    else:
        posts = conn.execute(
            'SELECT * FROM posts WHERE author = ? AND (hidden IS NULL OR hidden = 0) ORDER BY created_at DESC',
            (username,)
        ).fetchall()
    
    conn.close()
    
    result = []
    for post in posts:
        post_dict = dict(post)
        result.append(post_dict)
    
    return jsonify(result)

# ---------- 管理端 ----------
@app.route('/admin')
def admin_page():
    return send_from_directory('static/admin', 'index.html')

# ---------- 管理端 API ----------
@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def admin_stats():
    conn = get_db()
    
    users_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    posts_count = conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
    comments_count = conn.execute('SELECT COUNT(*) FROM comments').fetchone()[0]
    flowers_count = conn.execute('SELECT COUNT(*) FROM user_flowers').fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'users': users_count,
        'posts': posts_count,
        'comments': comments_count,
        'flowers': flowers_count
    })

# ---------- 获取所有用户 ----------
@app.route('/api/admin/users', methods=['GET'])
@admin_required
def admin_users():
    conn = get_db()
    users = conn.execute('SELECT id, username, created_at, avatar FROM users ORDER BY id DESC').fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

# ---------- 删除用户 ----------
@app.route('/api/admin/users/<username>', methods=['DELETE'])
@admin_required
def admin_delete_user(username):
    conn = get_db()
    conn.execute('DELETE FROM posts WHERE author = ?', (username,))
    conn.execute('DELETE FROM comments WHERE author = ?', (username,))
    conn.execute('DELETE FROM post_likes WHERE username = ?', (username,))
    conn.execute('DELETE FROM follows WHERE follower = ? OR following = ?', (username, username))
    conn.execute('DELETE FROM checkins WHERE username = ?', (username,))
    conn.execute('DELETE FROM user_flowers WHERE username = ?', (username,))
    conn.execute('DELETE FROM users WHERE username = ?', (username,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'msg': '用户已删除'})

# ---------- 获取所有帖子（管理端） ----------
@app.route('/api/admin/posts', methods=['GET'])
@admin_required
def admin_posts():
    conn = get_db()
    posts = conn.execute('SELECT * FROM posts ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict(p) for p in posts])

# ---------- 删除帖子（管理端） ----------
@app.route('/api/admin/posts/<int:post_id>', methods=['DELETE'])
@admin_required
def admin_delete_post(post_id):
    conn = get_db()
    conn.execute('DELETE FROM comments WHERE post_id = ?', (post_id,))
    conn.execute('DELETE FROM post_likes WHERE post_id = ?', (post_id,))
    conn.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'msg': '帖子已删除'})

# ---------- 管理员登录 ----------
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    conn = get_db()
    admin = conn.execute('SELECT * FROM admins WHERE username = ?', (username,)).fetchone()
    conn.close()
    
    if not admin or not check_password_hash(admin['password'], password):
        return jsonify({'status': 'error', 'msg': '用户名或密码错误'}), 401
    
    # 写入 session（关键安全改动）
    session['admin_token'] = secrets.token_urlsafe(32)
    session['admin_user'] = username
    session.permanent = False
    
    return jsonify({'status': 'success', 'msg': '登录成功'})

# ---------- 管理员退出 ----------
@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin_token', None)
    session.pop('admin_user', None)
    return jsonify({'status': 'success', 'msg': '已退出登录'})

# ---------- 获取公告 ----------
@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    conn = get_db()
    announcements = conn.execute('SELECT * FROM announcements ORDER BY created_at DESC LIMIT 10').fetchall()
    conn.close()
    return jsonify([dict(a) for a in announcements])

# ---------- 发布公告 ----------
@app.route('/api/admin/announcements', methods=['POST'])
@admin_required
def create_announcement():
    data = request.get_json()
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    media_type = data.get('media_type', 'text')
    media_url = data.get('media_url', '')
    
    if not title or not content:
        return jsonify({'status': 'error', 'msg': '标题和内容不能为空'}), 400
    
    conn = get_db()
    conn.execute('''INSERT INTO announcements (title, content, media_type, media_url) 
        VALUES (?, ?, ?, ?)''', (title, content, media_type, media_url))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'msg': '公告发布成功'})

# ---------- 删除公告 ----------
@app.route('/api/admin/announcements/<int:ann_id>', methods=['DELETE'])
@admin_required
def delete_announcement(ann_id):
    conn = get_db()
    conn.execute('DELETE FROM announcements WHERE id = ?', (ann_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'msg': '公告已删除'})

# ---------- 获取所有评论（管理端） ----------
@app.route('/api/admin/comments', methods=['GET'])
@admin_required
def admin_comments():
    conn = get_db()
    comments = conn.execute('SELECT * FROM comments ORDER BY created_at DESC').fetchall()
    conn.close()
    result = []
    for c in comments:
        comment = dict(c)
        comment['post_title'] = ''
        result.append(comment)
    return jsonify(result)

# ---------- 删除评论（管理端） ----------
@app.route('/api/admin/comments/<int:comment_id>', methods=['DELETE'])
@admin_required
def admin_delete_comment(comment_id):
    conn = get_db()
    conn.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'msg': '评论已删除'})

# ---------- 导出数据 ----------
@app.route('/api/admin/export/<data_type>', methods=['GET'])
@admin_required
def export_data(data_type):
    import csv
    import io
    from datetime import datetime
    
    conn = get_db()
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    
    if data_type == 'users':
        users = conn.execute('SELECT id, username, created_at FROM users ORDER BY id').fetchall()
        writer.writerow(['ID', '用户名', '注册时间'])
        for u in users:
            writer.writerow([u['id'], u['username'], u['created_at']])
        filename = f'用户数据_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    elif data_type == 'posts':
        posts = conn.execute('SELECT id, title, author, views, likes, comments, created_at FROM posts ORDER BY id').fetchall()
        writer.writerow(['ID', '标题', '作者', '浏览', '点赞', '评论', '发布时间'])
        for p in posts:
            writer.writerow([p['id'], p['title'], p['author'], p['views'], p['likes'], p['comments'], p['created_at']])
        filename = f'帖子数据_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    elif data_type == 'comments':
        comments = conn.execute('SELECT id, post_id, author, content, created_at FROM comments ORDER BY id').fetchall()
        writer.writerow(['ID', '帖子ID', '作者', '内容', '时间'])
        for c in comments:
            writer.writerow([c['id'], c['post_id'], c['author'], c['content'], c['created_at']])
        filename = f'评论数据_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    else:
        conn.close()
        return jsonify({'status': 'error', 'msg': '类型错误'}), 400
    
    conn.close()
    output.seek(0)
    
    return Response(
    output.getvalue().encode('utf-8-sig'),  #  改为 utf-8-sig
    mimetype='text/csv; charset=utf-8',      #  添加 charset
    headers={'Content-Disposition': f'attachment;filename={filename.encode("ascii", "ignore").decode()}'}
)

# ========== 群组 API ==========

# 获取所有群组
@app.route('/api/groups', methods=['GET'])
def get_groups():
    conn = get_db()
    try:
        conn.execute("ALTER TABLE posts ADD COLUMN hidden INTEGER DEFAULT 0")
    except:
        pass
    
    groups = conn.execute('''
        SELECT g.*, 
               (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) as member_count,
               (SELECT COUNT(DISTINCT p.id) FROM posts p 
                INNER JOIN group_members gm ON p.author = gm.username 
                WHERE gm.group_id = g.id AND (p.hidden IS NULL OR p.hidden = 0)) as post_count
        FROM groups_info g 
        ORDER BY g.created_at DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(g) for g in groups])

# 获取用户加入的群组
@app.route('/api/user/<username>/groups', methods=['GET'])
def get_user_groups(username):
    conn = get_db()
    try:
        conn.execute("ALTER TABLE posts ADD COLUMN hidden INTEGER DEFAULT 0")
    except:
        pass
    
    groups = conn.execute('''
        SELECT g.*, 
               (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) as member_count,
               (SELECT COUNT(DISTINCT p.id) FROM posts p 
                INNER JOIN group_members gm2 ON p.author = gm2.username 
                WHERE gm2.group_id = g.id AND (p.hidden IS NULL OR p.hidden = 0)) as post_count,
               gm.role as user_role
        FROM groups_info g
        JOIN group_members gm ON g.id = gm.group_id
        WHERE gm.username = ?
        ORDER BY g.created_at DESC
    ''', (username,)).fetchall()
    conn.close()
    return jsonify([dict(g) for g in groups])

# 创建群组
@app.route('/api/groups', methods=['POST'])
def create_group():
    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    creator = data.get('creator', '').strip()
    
    if not name or not creator:
        return jsonify({'status': 'error', 'msg': '群组名称和创建者不能为空'}), 400
    
    conn = get_db()
    try:
        cursor = conn.execute(
            'INSERT INTO groups_info (name, description, creator) VALUES (?, ?, ?)',
            (name, description, creator)
        )
        group_id = cursor.lastrowid
        
        # 创建者自动成为管理员
        conn.execute(
            'INSERT INTO group_members (group_id, username, role) VALUES (?, ?, ?)',
            (group_id, creator, 'admin')
        )
        
        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'msg': '群组创建成功', 'group_id': group_id})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'status': 'error', 'msg': '群组名已存在'}), 409

# 获取群组详情
@app.route('/api/groups/<int:group_id>', methods=['GET'])
def get_group_detail(group_id):
    conn = get_db()
    try:
        conn.execute("ALTER TABLE posts ADD COLUMN hidden INTEGER DEFAULT 0")
    except:
        pass
    
    group = conn.execute('''
        SELECT g.*, 
               (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) as member_count,
               (SELECT COUNT(DISTINCT p.id) FROM posts p 
                INNER JOIN group_members gm ON p.author = gm.username 
                WHERE gm.group_id = g.id AND (p.hidden IS NULL OR p.hidden = 0)) as post_count
        FROM groups_info g WHERE g.id = ?
    ''', (group_id,)).fetchone()
    
    if not group:
        conn.close()
        return jsonify({'status': 'error', 'msg': '群组不存在'}), 404
    
    # 获取成员列表
    members = conn.execute('''
        SELECT gm.username, gm.role, gm.joined_at, u.avatar
        FROM group_members gm
        LEFT JOIN users u ON gm.username = u.username
        WHERE gm.group_id = ?
        ORDER BY 
            CASE gm.role 
                WHEN 'admin' THEN 1 
                WHEN 'moderator' THEN 2 
                ELSE 3 
            END,
            gm.joined_at ASC
    ''', (group_id,)).fetchall()
    
    conn.close()
    
    result = dict(group)
    result['members'] = [dict(m) for m in members]
    
    return jsonify({'status': 'success', 'group': result})

# 加入群组
@app.route('/api/groups/<int:group_id>/join', methods=['POST'])
def join_group(group_id):
    data = request.get_json()
    username = data.get('username', '').strip()
    
    if not username:
        return jsonify({'status': 'error', 'msg': '请先登录'}), 401
    
    conn = get_db()
    
    try:
        conn.execute(
            'INSERT INTO group_members (group_id, username, role) VALUES (?, ?, ?)',
            (group_id, username, 'member')
        )
        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'msg': '加入成功'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'status': 'error', 'msg': '已经是群组成员'}), 409

# 退出群组
@app.route('/api/groups/<int:group_id>/leave', methods=['POST'])
def leave_group(group_id):
    data = request.get_json()
    username = data.get('username', '').strip()
    
    if not username:
        return jsonify({'status': 'error', 'msg': '请先登录'}), 401
    
    conn = get_db()
    
    # 检查是否是创建者
    group = conn.execute('SELECT creator FROM groups_info WHERE id = ?', (group_id,)).fetchone()
    if group and group['creator'] == username:
        conn.close()
        return jsonify({'status': 'error', 'msg': '群主不能退出群组'}), 400
    
    conn.execute('DELETE FROM group_members WHERE group_id = ? AND username = ?',
                (group_id, username))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'msg': '已退出群组'})

# 邀请成员（仅群主和管理员可用）
@app.route('/api/groups/<int:group_id>/invite', methods=['POST'])
def invite_member(group_id):
    data = request.get_json()
    operator = data.get('operator', '').strip()
    username = data.get('username', '').strip()
    
    if not operator or not username:
        return jsonify({'status': 'error', 'msg': '参数错误'}), 400
    
    conn = get_db()
    
    operator_info = conn.execute(
        'SELECT role FROM group_members WHERE group_id = ? AND username = ?',
        (group_id, operator)
    ).fetchone()
    
    if not operator_info or operator_info['role'] not in ('admin', 'moderator'):
        conn.close()
        return jsonify({'status': 'error', 'msg': '只有群主和管理员才能邀请成员'}), 403
    
    user = conn.execute('SELECT username FROM users WHERE username = ?', (username,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'status': 'error', 'msg': '用户不存在'}), 404
    
    existing = conn.execute(
        'SELECT id FROM group_members WHERE group_id = ? AND username = ?',
        (group_id, username)
    ).fetchone()
    
    if existing:
        conn.close()
        return jsonify({'status': 'error', 'msg': '该用户已经是群组成员'}), 409
    
    try:
        conn.execute(
            'INSERT INTO group_members (group_id, username, role) VALUES (?, ?, ?)',
            (group_id, username, 'member')
        )
        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'msg': f'成功邀请 {username} 加入群组'})
    except Exception as e:
        conn.close()
        return jsonify({'status': 'error', 'msg': f'邀请失败: {str(e)}'}), 500

# 获取群组帖子 - 显示群组成员的所有帖子
@app.route('/api/groups/<int:group_id>/posts', methods=['GET'])
def get_group_posts(group_id):
    conn = get_db()
    
    try:
        conn.execute("ALTER TABLE posts ADD COLUMN hidden INTEGER DEFAULT 0")
    except:
        pass
    
    # 获取群组所有成员的用户名
    members = conn.execute(
        'SELECT username FROM group_members WHERE group_id = ?',
        (group_id,)
    ).fetchall()
    
    member_usernames = [m['username'] for m in members]
    
    if not member_usernames:
        conn.close()
        return jsonify([])
    
    # 构建 IN 查询的占位符
    placeholders = ','.join(['?' for _ in member_usernames])
    
    # 查询这些成员发的帖子（只显示未隐藏的）
    posts = conn.execute(
        f'''SELECT p.* 
            FROM posts p
            WHERE p.author IN ({placeholders})
            AND (p.hidden IS NULL OR p.hidden = 0)
            ORDER BY p.created_at DESC''',
        member_usernames
    ).fetchall()
    
    conn.close()
    
    result = []
    for post in posts:
        post_dict = dict(post)
        conn2 = get_db()
        author = conn2.execute('SELECT avatar FROM users WHERE username = ?', 
                              (post_dict['author'],)).fetchone()
        conn2.close()
        
        if author and author['avatar']:
            post_dict['author_avatar'] = author['avatar']
        else:
            post_dict['author_avatar'] = f'/api/default-avatar?name={post_dict["author"]}'
        
        result.append(post_dict)
    
    return jsonify(result)

# 群组搜索
@app.route('/api/groups/search', methods=['GET'])
def search_groups():
    keyword = request.args.get('q', '').strip()
    
    if not keyword:
        return jsonify([])
    
    conn = get_db()
    search_pattern = f'%{keyword}%'
    groups = conn.execute('''
        SELECT g.*, 
               (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) as member_count
        FROM groups_info g 
        WHERE g.name LIKE ? OR g.description LIKE ?
        ORDER BY g.created_at DESC
    ''', (search_pattern, search_pattern)).fetchall()
    conn.close()
    
    return jsonify([dict(g) for g in groups])

@app.route('/group')
def group_page():
    return send_from_directory('static', 'group.html')

# ========== 群组聊天 API ==========

# 群聊消息表（自动创建）
def init_chat_table():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS group_chat (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

# 获取群聊消息
@app.route('/api/groups/<int:group_id>/chat', methods=['GET'])
def get_group_chat(group_id):
    init_chat_table()
    conn = get_db()
    messages = conn.execute(
        'SELECT * FROM group_chat WHERE group_id = ? ORDER BY created_at ASC LIMIT 100',
        (group_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(m) for m in messages])

# 发送群聊消息
@app.route('/api/groups/<int:group_id>/chat', methods=['POST'])
def send_group_chat(group_id):
    data = request.get_json()
    username = data.get('username', '').strip()
    content = data.get('content', '').strip()
    
    if not username or not content:
        return jsonify({'status': 'error', 'msg': '消息不能为空'}), 400
    
    init_chat_table()
    conn = get_db()
    
    # 检查是否是群成员
    member = conn.execute(
        'SELECT id FROM group_members WHERE group_id = ? AND username = ?',
        (group_id, username)
    ).fetchone()
    
    if not member:
        conn.close()
        return jsonify({'status': 'error', 'msg': '只有群成员才能发言'}), 403
    
    conn.execute(
        'INSERT INTO group_chat (group_id, username, content) VALUES (?, ?, ?)',
        (group_id, username, content)
    )
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'success', 'msg': '发送成功'})

# ---------- 启动服务 ----------
# 修改后（兼容 Railway）
if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
