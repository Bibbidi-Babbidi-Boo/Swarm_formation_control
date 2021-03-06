#!/usr/bin/env python
import rospy
import tf
from math import *
import sympy
from sympy import solve
from sympy import Symbol
import time
import numpy as np
from scipy.optimize import minimize
import time

from std_msgs.msg import Float64
from sensor_msgs.msg import Imu
from gazebo_msgs.msg import ModelStates

rospy.init_node('p2p', anonymous=True)

bot_no = input("Enter bot number: ")
name = 'bot' + str(bot_no)
goal_x = input("Enter goal x: ")
goal_y = input("Enter goal y: ")

pub1 = rospy.Publisher("/"+name+"/wheel_joint1_controller/command", Float64, queue_size=1)
pub2 = rospy.Publisher("/"+name+"/wheel_joint2_controller/command", Float64, queue_size=1)
pub3 = rospy.Publisher("/"+name+"/wheel_joint3_controller/command", Float64, queue_size=1)

goal_xprev = 0.0
goal_yprev = 0.0
sum_x = 0.0
sum_y = 0.0 
pos = 0
obstacle = []
tau = 1
v_max = sqrt(1**2 + 1**2)
flag = 0
res = []


########## Assuming we know the position and orientation of the robot, here we directly take the data from gazebo model_state ###########

def callback(data):
	global pos, bot_no, obstacle, v_max, tau
	obstacle = []
	w = 0

	v1 = Symbol('v1')
	v2 = Symbol('v2')
	v3 = Symbol('v3')

	if pos == 0:
		for i in range (1, len(data.name)):
			if data.name[i] == name:
				pos = i

	x = data.pose[pos].position.x
	y = data.pose[pos].position.y

	a = data.pose[pos].orientation.x
	b = data.pose[pos].orientation.y
	c = data.pose[pos].orientation.z
	d = data.pose[pos].orientation.w
	l = [a,b,c,d]

	vel_curx = data.twist[pos].linear.x
	vel_cury = data.twist[pos].linear.y

	roll, pitch, yaw = tf.transformations.euler_from_quaternion(l)

	for i in range (1, len(data.name)):
		if i!= pos:
			if dist(x, y, data.pose[i].position.x, data.pose[i].position.y) - 2*0.42 < 2*v_max*tau:
				obstacle.append([data.pose[i].position.x, data.pose[i].position.y, data.twist[i].linear.x, data.twist[i].linear.y])

	

	v_1, v_2 = goal_pid(x,y)

	v_x, v_y = ORCA(v_1, v_2, x, y, vel_curx, vel_cury)


	###########			v_x, v_y, w are body linear and angular velocities. For now take them from user ##################
	###########			v1, v2, v3 are velocities at the COM of wheel. Divide by r_wheel to get ang vel for wheel ########

	sol = solve([-v_x+v1*sin(yaw)+v2*sin(np.pi/3-yaw)-v3*sin(np.pi/3+yaw), -v_y-v1*cos(yaw)+v2*cos(np.pi/3-yaw)+v3*cos(np.pi/3+yaw), -w+ (v1+v2+v3)/0.35], dict=True, rational=False, simplify=False)

	v1 = sol[0][v1]/0.065625
	v2 = sol[0][v2]/0.065625
	v3 = sol[0][v3]/0.065625


	pub1.publish(v1)
	pub2.publish(v2)
	pub3.publish(v3)



def ORCA(v_xpref, v_ypref, x, y, v1, v2):
	global v_max, tau, obstacle, res, flag
	v_opt = [v_xpref, v_ypref]

	if obstacle == []:
		return v_opt
	else:
		for i in range(len(obstacle)):

			## Center of the boundary circle in the velocity plane
			cx = (obstacle[i][0]-x)/tau
			cy = (obstacle[i][1]-y)/tau

			## Even zero vel doesnt prevent crash implies some error
			if dist(0,0,cx,cy)<0.42*2/tau:
				print("Something wrong")
				break

			## Current Velocities
			v_cur = [v1, v2]

			## relative velocities
			v_relx = v1-obstacle[i][2]
			v_rely = v2-obstacle[i][3]

			## Finding the two tangents to the circle in vel plane
			m = Symbol('m', real=True)
			m = solve(abs((cy-m*cx)/sympy.sqrt(1+m**2))-(0.42*2/tau), m, rational=False, simplify=False)

			## If the vel lies between the tangents then it lies in the same halfplane as the center for both tangents
			if ((v_rely-m[0]*v_relx>0 and cy-m[0]*cx>0) or (v_rely-m[0]*v_relx<0 and cy-m[0]*cx<0)) and ((v_rely-m[1]*v_relx>0 and cy-m[1]*cx>0) or (v_rely-m[1]*v_relx<0 and cy-m[1]*cx<0)):
				flag+=1

				## Points where tangents meet the circle (x1,y1), (x2,y2)
				a = Symbol('a',real=True)
				x1 = solve(m[0]*a-(-a/m[0] + cy + cx/m[0]), rational=False, simplify=False)
				x1 = float(x1[0])
				y1 = float(m[0]*x1)
				x2 = solve(m[1]*a-(-a/m[1] + cy + cx/m[1]), rational=False, simplify=False)
				x2 = float(x2[0])
				y2 = float(m[1]*x2)

				## If point lies within the tangent,center,origin triangle, the resulting area of the three triangles formed adds up to the main area
				if ((area(v_relx,v_rely,x1,y1,cx,cy) + area(cx,cy,v_relx,v_rely,0,0) + area(v_relx,v_rely,x1,y1,0,0) == area(cx,cy,0,0,x1,y1)) or (area(v_relx,v_rely,x2,y2,cx,cy) + area(cx,cy,v_relx,v_rely,0,0) + area(v_relx,v_rely,x2,y2,0,0) == area(cx,cy,0,0,x2,y2))) and dist(v_relx,v_rely,cx,cy)<=0.42*2/tau:
					d_min = 0.42*2/tau - dist(cx,cy,v_relx,v_rely)
					theta_min = atan2(v_rely-cy, v_relx-cx)
					if dist(v_relx,v_rely,cx,cy)>dist(v_relx+cos(theta_min),v_rely+sin(theta_min),cx,cy):
							theta_min = theta_min+np.pi
					print("1")

				else:

					## Comparing the distance of the point from the two tangent lines
					if dist_from_line(v_relx,v_rely,m[0],0) < dist_from_line(v_relx,v_rely,m[1],0):
						d_min = dist_from_line(v_relx,v_rely,m[0],0)
						theta_min = atan2(-1/m[0],1)
						## In case of reversed theta
						if dist_from_line(v_relx,v_rely,m[0],0) < dist_from_line(v_relx+d_min*cos(theta_min),v_rely+d_min*sin(theta_min),m[0],0):
							theta_min += np.pi
							print("True")
						print("2")
					elif dist_from_line(v_relx,v_rely,m[1],0) <= dist_from_line(v_relx,v_rely,m[0],0):
						d_min = dist_from_line(v_relx,v_rely,m[1],0)
						theta_min = atan2(-1/m[1],1)
						if dist_from_line(v_relx,v_rely,m[1],0) < dist_from_line(v_relx+d_min*cos(theta_min),v_rely+d_min*sin(theta_min),m[1],0):
							theta_min += np.pi
							print("True")
						print("3")
					else:
						print("Error")

				n = [cos(theta_min), sin(theta_min)]
				u = [d_min*cos(theta_min), d_min*sin(theta_min)]
				v_opt = np.array(v_opt, dtype=Float64)
				u = np.array(u, dtype=Float64)
				n = np.array(n, dtype=Float64)
				#print(u)

				fun = lambda v: np.sqrt((v[0]-v_opt[0])**2 + (v[1]-v_opt[1])**2)

				cons = ({'type': 'ineq', 'fun': lambda v: np.dot((v-(v_cur+1*u)),n)},
						{'type': 'ineq', 'fun': lambda v: 1-v[0]},
						{'type': 'ineq', 'fun': lambda v: v[0]+1},
						{'type': 'ineq', 'fun': lambda v: v[1]+1},
						{'type': 'ineq', 'fun': lambda v: 1-v[1]})
				r = minimize(fun, (v_opt[0],v_opt[1]), constraints=cons)
				res = [r.x[0], r.x[1]]
				
				#res = v_opt + u
				if (((res[1]-obstacle[i][3])-m[0]*(res[0]-obstacle[i][2])>0 and ((obstacle[i][1]-y-res[1]*tau)/tau)-m[0]*((obstacle[i][0]-x-res[0]*tau)/tau)>0) or ((res[1]-obstacle[i][3])-m[0]*(res[0]-obstacle[i][2])<0 and ((obstacle[i][1]-y-res[1]*tau)/tau)-m[0]*((obstacle[i][0]-x-res[0]*tau)/tau)<0)) and (((res[1]-obstacle[i][3])-m[1]*(res[0]-obstacle[i][2])>0 and ((obstacle[i][1]-y-res[1]*tau)/tau)-m[1]*((obstacle[i][0]-x-res[0]*tau)/tau)>0) or ((res[1]-obstacle[i][3])-m[1]*(res[0]-obstacle[i][2])<0 and ((obstacle[i][1]-y-res[1]*tau)/tau)-m[1]*((obstacle[i][0]-x-res[0]*tau)/tau)<0)):
					print("It isnt avoiding")
			else:
				#if dist(x+v_opt[0]*tau, y+v_opt[1]*tau, obstacle[i][0], obstacle[i][1]) < 2*0.42:
				#	print("Pass")
				#	pass
				#else:
				print("Else")
				res = v_opt	

		return res


def dist(x1, y1, x2, y2):
	d = np.sqrt((x2-x1)**2 + (y2-y1)**2)
	return d

def dist_from_line(x0, y0, m, c):
	d = abs((y0-m*x0-c)/sqrt(1+m**2))
	return d

def area(x1, y1, x2, y2, x3, y3):
	a = (x1*(y2-y3) + x2*(y3-y1) + x3*(y1-y2))/2
	return a


def goal_pid(x,y):
	global goal_x, goal_y, goal_xprev, goal_yprev, sum_x, sum_y

	kp = 1
	ki = 0.001
	kd = 0.5

	vx = kp*(goal_x-x) + kd*(goal_x-goal_xprev) + ki*sum_x
	vy = kp*(goal_y-y) + kd*(goal_y-goal_yprev) + ki*sum_y

	goal_xprev = goal_x
	goal_yprev = goal_y
	sum_x += goal_x-x
	sum_y = goal_y-y

	if vx>1:
		vx = 1
	if vx<-1:
		vx = -1
	if vy>1:
		vy = 1
	if vy<-1:
		vy = -1

	return vx,vy


def listener ():
	rospy.Subscriber("/gazebo/model_states", ModelStates, callback, queue_size=1)
	rospy.spin()

if __name__ == '__main__':
	try:
		listener()
	except rospy.ROSInterruptException:
		pass