# GitHub 上传说明

您的项目文件已经准备好上传到 GitHub，但需要您提供认证信息。

## 第一步：创建 GitHub Personal Access Token

1. 访问 https://github.com/settings/tokens
2. 点击 "Generate new token"
3. 选择 "Fine-grained personal access tokens" 或 "Personal access tokens" 
4. 设置适当的权限（repo 权限）
5. 复制生成的 token

## 第二步：上传项目

有两种方式可以完成上传：

### 方式一：使用 HTTPS + Token
```bash
cd "/mnt/d/桌面/comfyui-flyway"

# 设置 git 凭据
git remote set-url origin https://fllywaay:[YOUR_TOKEN]@github.com/fllywaay/comfyui-flyway.git

# 推送项目
git push -u origin main
```

### 方式二：使用 SSH（推荐）
1. 生成 SSH 密钥：
```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```

2. 将 SSH 公钥添加到 GitHub：
   - 复制公钥内容：`cat ~/.ssh/id_ed25519.pub`
   - 访问 https://github.com/settings/keys
   - 点击 "New SSH key"
   - 粘贴公钥内容并保存

3. 更改远程 URL 到 SSH：
```bash
git remote set-url origin git@github.com:fllywaay/comfyui-flyway.git
git push -u origin main
```

## 第三步：在 ComfyUI Manager 中添加插件

上传完成后：
1. 访问 https://github.com/ltdrdata/ComfyUI-Manager
2. 按照说明添加您的仓库 URL：https://github.com/fllywaay/comfyui-flyway

您的项目已经准备就绪，只需要完成认证步骤即可上传！