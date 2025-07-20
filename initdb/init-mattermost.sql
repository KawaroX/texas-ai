-- 创建 Mattermost 专用用户
CREATE USER mmuser WITH PASSWORD 'mmuser_password';

-- 创建 Mattermost 专用数据库
CREATE DATABASE mattermost;

-- 授予用户对数据库的权限
GRANT ALL PRIVILEGES ON DATABASE mattermost TO mmuser;

-- 为更好的性能优化设置
ALTER DATABASE mattermost SET default_transaction_isolation TO 'read committed';
ALTER DATABASE mattermost SET timezone TO 'UTC';
