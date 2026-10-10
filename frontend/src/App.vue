<template>
  <div id="app" :class="{ 'graph-page': $route.name === 'GraphView' }">
    <el-container>
      <el-header>
        <div class="header-content">
          <h1 class="logo">知识图谱系统</h1>
          <el-menu mode="horizontal" :router="true" :default-active="$route.path" class="nav-menu">
            <el-menu-item index="/">首页</el-menu-item>
            <el-menu-item index="/graph">图谱可视化</el-menu-item>
            <el-menu-item index="/projects">项目管理</el-menu-item>
          </el-menu>
        </div>
      </el-header>

      <el-main>
        <router-view />
      </el-main>

      <el-footer v-if="$route.name !== 'GraphView'">
        <p>Kgraph 多项目知识图谱系统 v2.0 | Powered by FastAPI + Vue 3 + Neo4j</p>
      </el-footer>
    </el-container>
  </div>
</template>

<script setup>
</script>

<style>
html, body { margin: 0; }
.graph-page > .el-container { height: 100dvh; min-height: 0; }
.graph-page .el-main { min-height: 0; padding: 10px; overflow: hidden; }

#app {
  font-family: 'Arial', 'Microsoft YaHei', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.el-container {
  min-height: 100vh;
}

.el-header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 0 20px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.1);
}

.header-content {
  display: flex;
  align-items: center;
  height: 60px;
  max-width: 1400px;
  margin: 0 auto;
}

.logo {
  font-size: 24px;
  font-weight: bold;
  margin: 0 30px 0 0;
  color: white;
}

.nav-menu {
  flex: 1;
  background: transparent;
  border: none;
}

.nav-menu.el-menu--horizontal {
  border-bottom: none;
}

.nav-menu .el-menu-item {
  color: rgba(255,255,255,0.9);
  font-size: 16px;
}

.nav-menu .el-menu-item:hover,
.nav-menu .el-menu-item.is-active {
  color: white;
  background: rgba(255,255,255,0.2);
}

.el-main {
  padding: 20px;
  background: #f5f7fa;
  min-height: calc(100vh - 120px);
}

.el-footer {
  background: #2c3e50;
  color: white;
  text-align: center;
  padding: 15px;
  line-height: 1.5;
}
</style>
