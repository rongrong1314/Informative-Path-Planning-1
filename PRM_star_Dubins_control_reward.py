from Node import Node
import dubins_path_planner as plan
import Config
from scipy.interpolate import interp1d
from true_field import true_field
import random
import math
import copy
import numpy as np
import time
import matplotlib.pyplot as plt


class PRM_star_Dubins:
	# PRM* algorithm using reward as variance/length with bias towards longer paths

	def __init__(self, start, space, obstacles, var_x=None, gmrf_params=None, max_iter=30, max_dist=25, min_dist=3, max_curvature=1.0):
		"""
		:param start: [x,y] starting location
		:param space: [min,max] bounds on square space
		:param obstacles: list of square obstacles
		:param growth: size of growth each new sample
		:param max_iter: max number of iterations for algorithm
		"""
		self.start = Node(start)
		self.node_list = [self.start]
		self.space = space
		self.max_iter = max_iter
		self.max_dist = max_dist
		self.min_dist = min_dist
		self.obstacles = obstacles
		self.var_x = var_x
		self.gmrf_params = gmrf_params
		self.max_curvature = max_curvature
		self.local_planner_time = 0.0
		self.method_time = 0.0

	def control_algorithm(self):
		for i in range(self.max_iter):
			sample_node = self.get_sample()

			if self.check_collision(sample_node):
				near_nodes = self.get_near_nodes(sample_node)
				new_node = self.set_parent(sample_node, near_nodes)
				if new_node is None:  # no possible path from any of the near nodes
					continue
				self.node_list.append(new_node)
				self.rewire(new_node, near_nodes)
			# animate added edges
			# self.draw_graph()

		# generate path
		last_node = self.get_best_last_node()
		if last_node is None:
			return None
		path, u_optimal, tau_optimal = self.get_path(last_node)
		return path, u_optimal, tau_optimal, self.local_planner_time, self.method_time

	def get_sample(self):
		sample = Node([random.uniform(self.space[0], self.space[1]),
					   random.uniform(self.space[2], self.space[3]),
					   random.uniform(-math.pi, math.pi)])
		return sample

	def steer(self, source_node, destination_node):
		# take source_node and find path to destination_node
		time1 = time.time()
		px, py, pangle, mode, plength, u = plan.dubins_path_planning(source_node.pose[0], source_node.pose[1], source_node.pose[2], destination_node.pose[0], destination_node.pose[1], destination_node.pose[2], self.max_curvature)
		self.local_planner_time += time.time() - time1
		new_node = copy.deepcopy(source_node)
		new_node.pose = destination_node.pose
		new_node.path_x = px
		new_node.path_y = py
		new_node.path_angle = pangle
		new_node.u = u
		new_node.dist += plength
		new_node.gain += self.reward(px, py, pangle)
		new_node.parent = source_node
		return new_node

	def set_parent(self, sample_node, near_nodes):
		# connects new_node along a maximum reward path
		if not near_nodes:
			near_nodes.append(self.nearest_node(sample_node))
		gain_list = []
		for near_node in near_nodes:
			temp_node = self.steer(near_node, sample_node)
			if self.check_collision(temp_node) and self.max_dist >= temp_node.dist:
				gain_list.append(temp_node.gain / temp_node.dist)
			else:
				gain_list.append(float("-inf"))

		max_gain = max(gain_list)
		max_node = near_nodes[gain_list.index(max_gain)]
		new_node = self.steer(max_node, sample_node)

		if new_node.gain == float("-inf"):
			print("max gain is -inf")
			return None
		return new_node

	def get_best_last_node(self):
		gain_list = []
		for node in self.node_list:
			if node.dist >= self.min_dist:
				gain_list.append(node.gain / node.dist)
			else:
				gain_list.append(float("-inf"))
		best_node = self.node_list[gain_list.index(max(gain_list))]
		return best_node

	def get_path(self, last_node):
		path = [last_node]
		u_optimal = []
		tau_optimal = np.vstack((last_node.path_x, last_node.path_y, last_node.path_angle))
		while True:
			path.append(last_node.parent)
			u_optimal = u_optimal + last_node.u
			last_node = last_node.parent
			if last_node is None:
				break
			tau_add = np.vstack((last_node.path_x, last_node.path_y, last_node.path_angle))
			tau_optimal = np.concatenate((tau_add, tau_optimal), axis=1)
		return path, u_optimal, tau_optimal

	def get_near_nodes(self, new_node):
		# gamma_star = 2(1+1/d) ** (1/d) volume(free)/volume(total) ** 1/d and we need gamma > gamma_star
		# for asymptotical completeness see Kalman 2011. gamma = 1 satisfies
		d = 2  # dimension of the self.space
		nnode = len(self.node_list)
		r = min(20.0 * ((math.log(nnode) / nnode)) ** (1 / d), 5.0)
		dlist = [dist(new_node, node) for node in self.node_list]
		near_nodes = [self.node_list[dlist.index(d)] for d in dlist if d <= r]
		return near_nodes

	def rewire(self, new_node, near_nodes):
		for near_node in near_nodes:
			temp_node = self.steer(new_node, near_node)
			if near_node.dist != 0:
				if near_node.gain / near_node.dist < temp_node.gain / temp_node.dist and self.check_collision(temp_node) and self.max_dist >= temp_node.dist:
					near_node.__dict__.update(vars(temp_node))

	def check_collision(self, node):
		if self.obstacles is not None:
			for (x, y, side) in self.obstacles:
				for (nx, ny) in zip(node.path_x, node.path_y):
					if ((nx > x - .8 * side / 2) & (nx < x + .8 * side / 2) & (ny > y - side / 2) & (
								ny < y + side / 2)):
						return False  # collision

		return True  # safe

	def nearest_node(self, sample):
		dlist = [dist(node, sample) for node in self.node_list]
		min_node = self.node_list[dlist.index(min(dlist))]
		return min_node

	def reward(self, px, py, pangle):
		control_cost = 0  # NOT USED!!!!!!
		var_reward = np.zeros(len(px))

		(lxf, lyf, dvx, dvy, lx, ly, n, p, de, l_TH, p_THETA, xg_min, xg_max, yg_min, yg_max) = self.gmrf_params
		A = np.zeros(shape=(n + p, 1)).astype(float)
		# iterate over path and calculate reward
		for kk in range(len(px)):  # Iterate over length of trajectory
			if not (self.space[0] <= px[kk] <= self.space[1]) or not (self.space[2] <= py[kk] <= self.space[3]):
				var_reward[kk] = -2  # Config.border_variance_penalty
				control_cost += 0
			else:
				p1 = time.time()
				A_z = Config.interpolation_matrix(np.array([px[kk], py[kk], pangle[kk]]), n, p, lx, xg_min, yg_min, de)
				var_reward[kk] = (np.dot(A_z.T, self.var_x)[0][0])
				control_cost += 0
				# A = A + Config.interpolation_matrix(np.array([px[kk], py[kk], pangle[kk]]), n, p, lx, xg_min, yg_min, de)  # for first summing then dotting
				self.method_time += (time.time() - p1)
		return np.sum(var_reward)

	def draw_graph(self, plot=None):
		if plot is None:  # use built in plt
			for node in self.node_list:
				plt.quiver(node.pose[0], node.pose[1], math.cos(node.pose[2]), math.sin(node.pose[2]))
				if node.parent is not None:
					plt.plot(node.path_x, node.path_y, 'yH', markersize=2)

			if self.obstacles is not None:
				for (x, y, side) in self.obstacles:
					plt.plot(x, y, "sk", ms=8 * side)

			plt.quiver(self.start.pose[0], self.start.pose[1], math.cos(self.start.pose[2]), math.sin(self.start.pose[2]), color="b")
			plt.axis(self.space)
			plt.grid(True)
			plt.title("PRM* (variance reward function)")
			plt.pause(.1)  # need for animation

		else:  # use plot of calling
			for node in self.node_list:
				plot.quiver(node.pose[0], node.pose[1], math.cos(node.pose[2]), math.sin(node.pose[2]))
				if node.parent is not None:
					plot.plot(node.path_x, node.path_y, 'yH', markersize=2)

			if self.obstacles is not None:
				for (x, y, side) in self.obstacles:
					plot.plot(x, y, "sk", ms=8 * side)

			plot.quiver(self.start.pose[0], self.start.pose[1], math.cos(self.start.pose[2]), math.sin(self.start.pose[2]), color="b")
			plot.axis(self.space)
			plot.grid(True)
			plot.title("PRM* (variance reward function)")
			plot.pause(.1)  # need for animation


def dist(node1, node2):
	# returns distance between two nodes
	return math.sqrt((node2.pose[0] - node1.pose[0]) ** 2 +
					 (node2.pose[1] - node1.pose[1]) ** 2 +
					 3 * min((node1.pose[2] - node2.pose[2]) ** 2, (node1.pose[2] - node2.pose[2] + 2 * math.pi) ** 2, (node1.pose[2] - node2.pose[2] - 2 * math.pi) ** 2))


# Calculate new observation vector through shape function interpolation
def interpolation_matrix(x_local2, n, p, lx, xg_min, yg_min, de):
	"""INTERPOLATION MATRIX:
	Define shape function matrix that maps grid vertices to
	continuous measurement locations"""
	u1 = np.zeros(shape=(n + p, 1)).astype(float)
	nx = int((x_local2[0] - xg_min) / de[0])  # Calculates the vertice column x-number at which the shape element starts.
	ny = int((x_local2[1] - yg_min) / de[1])  # Calculates the vertice row y-number at which the shape element starts.
	# Calculate position value in element coord-sys in meters
	x_el = float(0.1 * (x_local2[0] / 0.1 - int(x_local2[0] / 0.1))) - de[0] / 2
	y_el = float(0.1 * (x_local2[1] / 0.1 - int(x_local2[1] / 0.1))) - de[1] / 2
	# Define shape functions, "a" is element width in x-direction
	u1[(ny * lx) + nx] = (1 / (de[0] * de[1])) * ((x_el - de[0] / 2) * (y_el - de[1] / 2))  # u for lower left corner
	u1[(ny * lx) + nx + 1] = (-1 / (de[0] * de[1])) * ((x_el + de[0] / 2) * (y_el - de[1] / 2))  # u for lower right corner
	u1[((ny + 1) * lx) + nx] = (-1 / (de[0] * de[1])) * ((x_el - de[0] / 2) * (y_el + de[1] / 2))  # u for upper left corner
	u1[((ny + 1) * lx) + nx + 1] = (1 / (de[0] * de[1])) * ((x_el + de[0] / 2) * (y_el + de[1] / 2))  # u for upper right corner
	return u1


def main():
	start_time = time.time()
	# squares of [x,y,side length]
	obstacles = [
		(15, 17, 7),
		(4, 10, 6),
		(7, 23, 9),
		(22, 12, 5),
		(9, 15, 4)]

	# calling PRM*
	PRM_star = PRM_star_Dubins(start=[15.0, 28.0, np.deg2rad(0.0)], space=[0, 30, 0, 30], obstacles=obstacles)
	path, u_optimal, tau_optimal = PRM_star.control_algorithm()
	print(u_optimal)

	# plotting code
	PRM_star.draw_graph()
	if path[-1] is not None:
		plt.plot([node.pose[0] for node in path], [node.pose[1] for node in path], '-r')
	plt.grid(True)
	print("--- %s seconds ---" % (time.time() - start_time))
	plt.show()


if __name__ == '__main__':
	main()
