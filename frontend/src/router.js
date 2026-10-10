import { createRouter, createWebHistory } from 'vue-router'
import Home from './views/Home.vue'
import GraphView from './views/GraphView.vue'
import Projects from './views/Projects.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home
  },
  {
    path: '/graph',
    name: 'GraphView',
    component: GraphView
  },
  {
    path: '/projects',
    name: 'Projects',
    component: Projects
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router
