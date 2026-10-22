import { createRouter, createWebHistory } from 'vue-router'
import Home from './views/Home.vue'
import GraphView from './views/GraphView.vue'
import Projects from './views/Projects.vue'
import QuestionLocator from './views/QuestionLocator.vue'

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
  },
  {
    path: '/question-locator',
    name: 'QuestionLocator',
    component: QuestionLocator
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router
